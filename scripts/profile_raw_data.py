"""Audit every CSV record in the observed wide layout; not a CMS compliance validator."""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (ROOT / 'data/raw/cooper.csv', ROOT / 'data/raw/cape_regional.csv')
SOURCES = {
    'cooper.csv': 'https://request.cooperhealth.org/financial/210634462_Cooper-University-Hospital_standardcharges.csv',
    'cape_regional.csv': 'https://request.cooperhealth.org/financial/210662542_Cooper-University-Hospital-Cape-Regional_standardcharges.csv',
}
SUMMARY_FIELDS = {'median_amount', '10th_percentile', '90th_percentile', 'count', 'additional_payer_notes'}
NUMERIC_FIELDS = {'gross', 'discounted_cash', 'min', 'max', 'negotiated_dollar', 'negotiated_percentage', 'median_amount', '10th_percentile', '90th_percentile', 'count', 'drug_unit_of_measurement'}
NUMBER = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)')
csv.field_size_limit(10_000_000)


def payer_field(header: str) -> tuple[str, str, str] | None:
    """Summary and notes headers have a different shape from charge headers."""
    parts = header.split('|')
    if len(parts) == 4 and parts[0] == 'standard_charge':
        return parts[1], parts[2], parts[3]
    if len(parts) == 3 and parts[0] in SUMMARY_FIELDS:
        return parts[1], parts[2], parts[0]
    return None


def detect_layout(headers: list[str]) -> str:
    tall = {'payer_name', 'plan_name'}.issubset(headers)
    wide = any(payer_field(h) for h in headers)
    return 'mixed' if tall and wide else 'tall' if tall else 'wide' if wide else 'unknown'


def number(value: str) -> Decimal | None:
    if not NUMBER.fullmatch(value):
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def normalized_date(raw: str) -> str:
    for fmt in ('%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f'Unrecognized last_updated_on: {raw!r}')


def new_stats(numeric: bool, count_field: bool = False) -> dict:
    stats = {'blank': 0, 'nonblank': 0}
    if numeric:
        stats.update(valid_numeric=0, zero=0, positive=0, negative=0,
                     invalid_numeric=0, noninteger=0, invalid_examples=[], minimum=None, maximum=None)
    if count_field:
        stats.update(suppressed_1_through_10=0, invalid_count_value=0)
    return stats


def observe(stats: dict, raw: str) -> Decimal | None:
    value = raw.strip()
    if not value:
        stats['blank'] += 1
        return None
    stats['nonblank'] += 1
    if 'suppressed_1_through_10' in stats and value == '1 through 10':
        stats['suppressed_1_through_10'] += 1
        return None
    if 'valid_numeric' not in stats:
        return None
    parsed = number(value)
    if parsed is None:
        stats['invalid_numeric'] += 1
        if 'invalid_count_value' in stats:
            stats['invalid_count_value'] += 1
        if value not in stats['invalid_examples'] and len(stats['invalid_examples']) < 5:
            stats['invalid_examples'].append(value[:160])
        return None
    stats['valid_numeric'] += 1
    stats['zero' if parsed == 0 else 'positive' if parsed > 0 else 'negative'] += 1
    stats['noninteger'] += int(parsed != parsed.to_integral_value())
    if 'invalid_count_value' in stats:
        stats['invalid_count_value'] += int(parsed != parsed.to_integral_value() or not (parsed == 0 or parsed >= 11))
    for key, compare in (('minimum', min), ('maximum', max)):
        stats[key] = parsed if stats[key] is None else compare(stats[key], parsed)
    return parsed


def fingerprint(values: list[str]) -> bytes:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).digest()


def read_header(rows, path: Path) -> tuple[dict[str, str], list[str]]:
    """Read and validate the shared metadata and wide charge header."""
    try:
        metadata_headers, metadata_values, headers = [next(rows) for _ in range(3)]
    except StopIteration as exc:
        raise ValueError(f'{path}: expected two metadata records and a charge header') from exc
    if len(metadata_headers) != len(metadata_values):
        raise ValueError(f'{path}: metadata record widths differ')
    named_metadata = [h for h in metadata_headers if h.strip()]
    if len(set(named_metadata)) != len(named_metadata):
        raise ValueError(f'{path}: duplicate metadata names')
    if any(v.strip() for h, v in zip(metadata_headers, metadata_values) if not h.strip()):
        raise ValueError(f'{path}: nonblank metadata value has no header')
    metadata = {h: v for h, v in zip(metadata_headers, metadata_values) if h.strip()}
    if not headers or any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
        raise ValueError(f'{path}: blank or duplicate charge headers')
    required = {'description', 'setting', 'billing_class', 'modifiers', 'drug_unit_of_measurement', 'drug_type_of_measurement', 'code|1', 'code|1|type'}
    if not required.issubset(headers) or detect_layout(headers) != 'wide':
        raise ValueError(f'{path}: unsupported charge schema; expected observed wide layout')
    slots = [h for h in headers if re.fullmatch(r'code\|\d+', h)]
    if any(f'{h}|type' not in headers for h in slots):
        raise ValueError(f'{path}: code slot lacks a type column')
    # Retain the width separately for the profiler's existing audit output.
    return metadata, headers, len(metadata_headers) - len(named_metadata)


def profile(path: Path) -> dict:
    with path.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    result = {'file': path.name, 'source_url': SOURCES.get(path.name),
              'downloaded_at': None, 'size_bytes': path.stat().st_size, 'sha256': digest}
    with path.open(encoding='utf-8-sig', newline='') as file:
        rows = csv.reader(file, strict=True)
        metadata, headers, blank_metadata_headers = read_header(rows, path)
        slots = [h for h in headers if re.fullmatch(r'code\|\d+', h)]
        result.update(metadata=metadata, last_updated_on=normalized_date(metadata['last_updated_on']),
                      metadata_blank_headers=blank_metadata_headers,
                      columns=len(headers), layout='wide')
        specs = [payer_field(h) for h in headers]
        fields = [spec[2] if spec else h.split('|')[-1] for h, spec in zip(headers, specs)]
        stats = [new_stats(field in NUMERIC_FIELDS, field == 'count') for field in fields]
        pairs = sorted({spec[:2] for spec in specs if spec})
        result['payer_plans'] = [{'payer': p, 'plan': q} for p, q in pairs]
        categories = {h: Counter() for h in headers if h in {'setting', 'billing_class'} or h.endswith('|type')}
        methodologies = Counter()
        index = {h: i for i, h in enumerate(headers)}
        key_fields = [h for h in headers if h.startswith('code|')] + ['setting', 'billing_class', 'modifiers', 'drug_unit_of_measurement', 'drug_type_of_measurement']
        seen_rows, seen_keys = set(), set()
        quality = Counter(total_records=0, valid_width_records=0, malformed_records=0,
                          exact_duplicate_records=0, repeated_candidate_key_records=0,
                          incomplete_code_pairs=0, records_without_codes=0,
                          records_with_at_least_two_positive_dollars=0)
        malformed_examples = []
        for record, row in enumerate(rows, start=4):
            quality['total_records'] += 1
            if len(row) != len(headers):
                quality['malformed_records'] += 1
                if len(malformed_examples) < 5:
                    malformed_examples.append({'csv_record': record, 'width': len(row)})
                continue
            quality['valid_width_records'] += 1
            row_hash = fingerprint(row)
            quality['exact_duplicate_records'] += int(row_hash in seen_rows)
            seen_rows.add(row_hash)
            values = [v.strip() for v in row]
            key_hash = fingerprint([values[index[h]] for h in key_fields])
            quality['repeated_candidate_key_records'] += int(key_hash in seen_keys)
            seen_keys.add(key_hash)
            quality['records_without_codes'] += int(not any(values[index[h]] for h in slots))
            for h in slots:
                quality['incomplete_code_pairs'] += int(bool(values[index[h]]) != bool(values[index[f'{h}|type']]))
            for h, counts in categories.items():
                counts[values[index[h]]] += 1
            positive_dollars = 0
            for field, cell, stat in zip(fields, values, stats):
                parsed = observe(stat, cell)
                if field == 'negotiated_dollar' and parsed is not None and parsed > 0:
                    positive_dollars += 1
                if field == 'methodology':
                    methodologies[cell] += 1
            quality['records_with_at_least_two_positive_dollars'] += int(positive_dollars >= 2)
        result.update(quality=dict(quality), malformed_examples=malformed_examples,
                      candidate_key_fields=key_fields, categories={h: dict(c) for h, c in categories.items()},
                      methodologies=dict(methodologies), column_profiles=dict(zip(headers, stats)))
        groups = {}
        for field, stat in zip(fields, stats):
            group = groups.setdefault(field, Counter())
            for name, value in stat.items():
                if isinstance(value, int):
                    group[name] += value
        result['field_totals'] = {field: dict(counts) for field, counts in groups.items()}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='*', default=FILES)
    parser.add_argument('--output', type=Path, help='Write the audit artifact as JSON')
    args = parser.parse_args()
    try:
        profiles = [profile(path) for path in args.files]
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        print(f'Profile failed: {exc}', file=sys.stderr)
        return 1
    report = {'profile_version': 1, 'profiled_at_utc': datetime.now(timezone.utc).isoformat(), 'files': profiles}
    if args.output:
        if args.output.resolve() in {p.resolve() for p in args.files}:
            print('Output must not overwrite an input file', file=sys.stderr)
            return 1
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    for item in profiles:
        print(f"{item['file']}: {item['quality']['total_records']:,} records; {item['columns']} columns; {len(item['payer_plans'])} payer-plan pairs")
        print(f"  Quality: {json.dumps(item['quality'])}")
    return int(any(p['quality']['malformed_records'] for p in profiles))


if __name__ == '__main__':
    raise SystemExit(main())
