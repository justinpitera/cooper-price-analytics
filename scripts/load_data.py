"""Check the hospital CSVs, then load them into PostgreSQL.

Start at main() at the bottom to follow the steps. Each file is checked,
loaded in batches, and compared with its CSV report before the import is saved.
If a step fails, PostgreSQL rolls back that file's import.
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from itertools import islice
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.types.json import Jsonb

# Support both importing this module and running it directly from the terminal.
if __package__:
    from .profile_raw_data import FILES, ROOT, number, payer_field, profile, read_header
else:
    from profile_raw_data import FILES, ROOT, number, payer_field, profile, read_header

# Left side: CSV column name. Right side: database column name.
# Keep this order when sending rows to PostgreSQL's bulk import command (COPY).
# The original cells are also saved in service.raw_values for later checking.
SERVICE_FIELDS = {
    'description': 'description', 'setting': 'setting', 'billing_class': 'billing_class',
    'modifiers': 'modifiers', 'drug_unit_of_measurement': 'drug_unit_of_measurement',
    'drug_type_of_measurement': 'drug_type_of_measurement',
    'standard_charge|gross': 'gross', 'standard_charge|discounted_cash': 'discounted_cash',
    'standard_charge|min': 'published_min', 'standard_charge|max': 'published_max',
    'additional_generic_notes': 'additional_generic_notes',
}
SERVICE_NUMERIC = {'drug_unit_of_measurement', 'gross', 'discounted_cash', 'published_min', 'published_max'}
RATE_FIELDS = {
    'negotiated_dollar': 'negotiated_dollar', 'negotiated_percentage': 'negotiated_percentage',
    'negotiated_algorithm': 'negotiated_algorithm', 'methodology': 'methodology',
    'median_amount': 'median_amount', '10th_percentile': 'percentile_10',
    '90th_percentile': 'percentile_90', 'count': 'count_raw',
    'additional_payer_notes': 'additional_payer_notes',
}
RATE_NUMERIC = {'negotiated_dollar', 'negotiated_percentage', 'median_amount', 'percentile_10', 'percentile_90'}


def decimal_value(raw: str):
    """Read an exact decimal; a blank is missing, not a zero-dollar price."""
    value = raw.strip()
    if not value:
        return None
    parsed = number(value)
    if parsed is None:
        raise ValueError(f'Invalid numeric value: {raw!r}')
    return parsed


def count_values(raw: str):
    """Return (exact count, lower bound, upper bound) without guessing a range's value."""
    if raw.strip() == '1 through 10':
        return None, 1, 10
    parsed = decimal_value(raw)
    if parsed is None:
        return None, None, None
    if (parsed != parsed.to_integral_value() or not (parsed == 0 or parsed >= 11)
            or parsed > 9223372036854775807):
        raise ValueError(f'Invalid exact count: {raw!r}')
    return int(parsed), None, None


def layout(headers):
    """Find each column's position and group the price columns by insurer and plan."""
    index = {header: i for i, header in enumerate(headers)}
    base = set(SERVICE_FIELDS) | {f'code|{slot}{suffix}' for slot in range(1, 4) for suffix in ('', '|type')}
    plans = {}
    for header in headers:
        spec = payer_field(header)
        if spec:
            payer, plan, field = spec
            group = plans.setdefault((payer, plan), {})
            if field in group:
                raise ValueError(f'Duplicate payer field: {header}')
            group[field] = index[header]
        elif header not in base:
            raise ValueError(f'Unsupported column: {header}')
    if not base.issubset(index) or not plans:
        raise ValueError('Expected all service fields, three code slots, and payer-plan fields')
    # All nine fields must be present for every plan, even if some cells are blank.
    for pair, fields in plans.items():
        if set(fields) != set(RATE_FIELDS):
            raise ValueError(f'Incomplete or unsupported payer fields: {pair}')
    return index, sorted(plans.items())


def ensure_schema(connection):
    """Create any missing tables using the same SQL file as Docker setup."""
    with connection.transaction():
        # Serialize first-time DDL when two loaders start together.
        connection.execute('SELECT pg_advisory_xact_lock(208946319)')
        connection.execute((ROOT / 'sql/schema.sql').read_text())


def copy_rows(connection, table, columns, rows):
    """Send a batch to PostgreSQL at once; this is faster than one INSERT per row."""
    statement = sql.SQL('COPY analytics.{} ({}) FROM STDIN').format(
        sql.Identifier(table), sql.SQL(', ').join(map(sql.Identifier, columns)))
    with connection.cursor().copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def load_batch(connection, source_id, batch, index, plans):
    """Split CSV rows into services, their code slots, and their plan prices."""
    services, codes, rates = [], [], []
    for record, row in batch:
        if len(row) != len(index):
            raise ValueError(f'CSV record {record}: expected {len(index)} cells, got {len(row)}')
        try:
            values = [decimal_value(row[index[h]]) if column in SERVICE_NUMERIC
                      else row[index[h]].strip() for h, column in SERVICE_FIELDS.items()]
            services.append((source_id, record, *values, row))
            # Keep all three code slots, including empty ones.
            for slot in range(1, 4):
                codes.append((source_id, record, slot, row[index[f'code|{slot}']].strip(),
                              row[index[f'code|{slot}|type']].strip()))
            # Keep blank plan prices too, so we can measure price availability.
            for plan_id, (_, fields) in enumerate(plans, start=1):
                values = []
                for field, column in RATE_FIELDS.items():
                    raw = row[fields[field]]
                    values.append(decimal_value(raw) if column in RATE_NUMERIC
                                  else raw if field == 'count' else raw.strip())
                rates.append((source_id, record, plan_id, *values,
                              *count_values(row[fields['count']])))
        except ValueError as exc:
            raise ValueError(f'CSV record {record}: {exc}') from exc
    copy_rows(connection, 'service', ['source_file_id', 'csv_record', *SERVICE_FIELDS.values(), 'raw_values'], services)
    copy_rows(connection, 'service_code', ['source_file_id', 'csv_record', 'slot', 'code', 'code_type'], codes)
    copy_rows(connection, 'service_rate', ['source_file_id', 'csv_record', 'payer_plan_id',
                                         *RATE_FIELDS.values(), 'count_exact', 'count_lower', 'count_upper'], rates)


def reconcile_fields(connection, source_id, table, fields, numeric, audit):
    """Compare database field totals with the profiler's counts from the CSV."""
    expressions, checks = [], []
    for field, column in fields.items():
        if field == 'count':
            continue
        expected = audit['field_totals'][field.split('|')[-1]]
        col = sql.Identifier(column)
        # Missing numbers use NULL; missing text uses an empty string.
        conditions = {'blank': '{} IS NULL', 'nonblank': '{} IS NOT NULL'} if column in numeric else {
            'blank': "{} = ''", 'nonblank': "{} <> ''"}
        if column in numeric:
            conditions.update(valid_numeric='{} IS NOT NULL', zero='{} = 0',
                              positive='{} > 0', negative='{} < 0', noninteger='{} <> trunc({})')
        for stat, condition in conditions.items():
            predicate = sql.SQL(condition).format(col, col)
            expressions.append(sql.SQL('count(*) FILTER (WHERE {})').format(predicate))
            checks.append((f'{field}.{stat}', expected[stat]))
    query = sql.SQL('SELECT {} FROM analytics.{} WHERE source_file_id = %s').format(
        sql.SQL(', ').join(expressions), sql.Identifier(table))
    actual = connection.execute(query, (source_id,)).fetchone()
    for (name, expected), value in zip(checks, actual, strict=True):
        if value != expected:
            raise ValueError(f'Reconciliation failed for {name}: database={value}, source={expected}')


def reconcile(connection, source_id, audit):
    """Check that the import kept the expected rows, blanks, numbers, and count ranges."""
    expected_services = audit['quality']['total_records']
    expected_plans = len(audit['payer_plans'])
    expected_counts = {'service': expected_services, 'service_code': expected_services * 3,
                       'payer_plan': expected_plans, 'service_rate': expected_services * expected_plans}
    for table, expected in expected_counts.items():
        actual = connection.execute(sql.SQL('SELECT count(*) FROM analytics.{} WHERE source_file_id = %s')
                                    .format(sql.Identifier(table)), (source_id,)).fetchone()[0]
        if actual != expected:
            raise ValueError(f'Reconciliation failed for {table}: database={actual}, source={expected}')
    reconcile_fields(connection, source_id, 'service', SERVICE_FIELDS, SERVICE_NUMERIC, audit)
    reconcile_fields(connection, source_id, 'service_rate', RATE_FIELDS, RATE_NUMERIC, audit)
    actual = connection.execute('''
        SELECT count(*) FILTER (WHERE count_exact IS NULL AND count_lower IS NULL),
               count(count_exact), count(*) FILTER (WHERE count_exact = 0),
               count(*) FILTER (WHERE count_exact > 0), count(count_lower)
        FROM analytics.service_rate WHERE source_file_id = %s
    ''', (source_id,)).fetchone()
    stats = audit['field_totals']['count']
    expected = tuple(stats[k] for k in ('blank', 'valid_numeric', 'zero', 'positive', 'suppressed_1_through_10'))
    if actual != expected:
        raise ValueError(f'Count reconciliation failed: database={actual}, source={expected}')
    return expected_counts


def load_file(connection, path: Path):
    """Import one file, or check its existing import if we've already loaded it."""
    # Audit and parse the same private copy, even if the original download changes.
    with tempfile.TemporaryDirectory(prefix='cooper-load-') as directory:
        snapshot = Path(directory) / path.name
        shutil.copyfile(path, snapshot)
        with snapshot.open('rb') as file:
            digest = hashlib.file_digest(file, 'sha256').hexdigest()
        # The hash identifies file contents, even if the filename has changed.
        with connection.transaction():
            existing = connection.execute('SELECT id, audit FROM analytics.source_file WHERE sha256 = %s',
                                          (digest,)).fetchone()
            if existing:
                counts = reconcile(connection, existing[0], existing[1])
                return {'file': path.name, 'sha256': digest, 'status': 'already loaded', **counts}
        # Catch malformed rows and bad numbers before starting the import.
        audit = profile(snapshot)
        if audit['quality']['malformed_records']:
            raise ValueError(f"{path.name}: rejected {audit['quality']['malformed_records']} malformed records; no rows loaded")
        for field, stats in audit['field_totals'].items():
            if stats.get('invalid_numeric', 0) or stats.get('invalid_count_value', 0):
                raise ValueError(f'{path.name}: invalid numeric/count values in {field}; no rows loaded')
        # Everything below is one transaction: save the whole file or none of it.
        with snapshot.open(encoding='utf-8-sig', newline='') as file, connection.transaction():
            rows = csv.reader(file, strict=True)
            metadata, headers, _ = read_header(rows, snapshot)
            index, plans = layout(headers)
            if not metadata.get('version', '').strip():
                raise ValueError('Missing template version')
            # The unique hash also serializes concurrent imports of the same file.
            inserted = connection.execute('''
                INSERT INTO analytics.source_file
                    (sha256, filename, source_url, size_bytes, metadata, last_updated_on,
                     template_version, headers, audit)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sha256) DO NOTHING RETURNING id
            ''', (digest, path.name, audit['source_url'], audit['size_bytes'], Jsonb(metadata),
                  audit['last_updated_on'], metadata['version'], headers,
                  Jsonb(json.loads(json.dumps(audit, default=str))))).fetchone()
            if inserted is None:
                existing = connection.execute('SELECT id, audit FROM analytics.source_file WHERE sha256 = %s',
                                              (digest,)).fetchone()
                counts = reconcile(connection, existing[0], existing[1])
                return {'file': path.name, 'sha256': digest, 'status': 'already loaded', **counts}
            source_id = inserted[0]
            copy_rows(connection, 'payer_plan', ['source_file_id', 'id', 'payer', 'plan'],
                      ((source_id, i, *pair) for i, (pair, _) in enumerate(plans, start=1)))
            # The first three CSV records are metadata and column headers.
            records = enumerate(rows, start=4)
            # Small batches keep the full service/plan grid out of memory.
            while batch := list(islice(records, 500)):
                load_batch(connection, source_id, batch, index, plans)
            counts = reconcile(connection, source_id, audit)
        return {'file': path.name, 'sha256': digest, 'status': 'loaded', **counts}


def connect_database():
    """Read local settings from .env; DATABASE_URL can override them."""
    load_dotenv(ROOT / '.env')
    if os.environ.get('DATABASE_URL'):
        return psycopg.connect(os.environ['DATABASE_URL'], autocommit=True)
    return psycopg.connect(host='127.0.0.1', port=5432,
                          dbname=os.environ.get('POSTGRES_DB', 'cooper'),
                          user=os.environ.get('POSTGRES_USER', 'cooper'),
                          password=os.environ.get('POSTGRES_PASSWORD', 'cooperpass'), autocommit=True)


def main():
    """Connect, prepare the tables, and load the requested files (both by default)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*', type=Path, default=FILES)
    args = parser.parse_args()
    try:
        with connect_database() as connection:
            ensure_schema(connection)
            for path in args.files:
                print(f'Auditing/loading {path.name}...', flush=True)
                print(json.dumps(load_file(connection, path)), flush=True)
    except (OSError, ValueError, KeyError, csv.Error, psycopg.Error) as exc:
        print(f'Load failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
