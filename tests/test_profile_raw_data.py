"""Regression checks for data loss and misleading price/count interpretation."""
import csv
import tempfile
import unittest
from pathlib import Path

from scripts.profile_raw_data import new_stats, observe, payer_field, profile


class ProfileTests(unittest.TestCase):
    def write_csv(self, directory, rows, headers=None, metadata=None):
        path = Path(directory) / 'sample.csv'
        headers = headers or ['description', 'code|1', 'code|1|type', 'setting',
                              'billing_class', 'modifiers', 'drug_unit_of_measurement',
                              'drug_type_of_measurement',
                              'standard_charge|Payer|Plan, PPO|negotiated_dollar',
                              'count|Payer|Plan, PPO']
        with path.open('w', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerows([
                ['hospital_name', 'last_updated_on', ''],
                metadata or ['Test hospital', '7/1/2026', ''], headers, *rows])
        return path

    def test_suppressed_counts_are_not_missing_zero_or_invalid(self):
        stats = new_stats(True, count_field=True)
        for value in ['', '0', '1 through 10', '11', '3', '1.5', 'N/A']:
            observe(stats, value)
        self.assertEqual(stats['blank'], 1)
        self.assertEqual(stats['zero'], 1)
        self.assertEqual(stats['suppressed_1_through_10'], 1)
        self.assertEqual(stats['invalid_count_value'], 3)

    def test_numeric_tokens_are_not_silently_repaired(self):
        stats = new_stats(True)
        for value in ['NaN', 'Infinity', '$100', '1,000', 'N/A', '0', '-2', ' 12.50 ']:
            observe(stats, value)
        self.assertEqual(stats['invalid_numeric'], 5)
        self.assertEqual(stats['zero'], 1)
        self.assertEqual(stats['negative'], 1)
        self.assertEqual(stats['positive'], 1)
        self.assertEqual(str(stats['maximum']), '12.50')

    def test_full_scan_preserves_codes_and_flags_ambiguous_keys(self):
        row = ['Procedure, with comma\nand newline', '00123', 'CPT', 'outpatient', 'facility', '', '', '', '10', '1 through 10']
        with tempfile.TemporaryDirectory() as d:
            path = self.write_csv(d, [row, row, row[:-2] + ['20', '0'], ['too short']])
            result = profile(path)
        q = result['quality']
        self.assertEqual(q['total_records'], 4)
        self.assertEqual(q['malformed_records'], 1)
        self.assertEqual(q['exact_duplicate_records'], 1)
        self.assertEqual(q['repeated_candidate_key_records'], 2)
        self.assertEqual(result['last_updated_on'], '2026-07-01')
        self.assertEqual(result['metadata_blank_headers'], 1)
        self.assertEqual(result['field_totals']['negotiated_dollar']['nonblank'], 3)
        self.assertEqual(result['field_totals']['count']['suppressed_1_through_10'], 2)
        self.assertEqual(result['malformed_examples'][0]['csv_record'], 7)

    def test_bad_headers_and_unnamed_metadata_fail(self):
        with tempfile.TemporaryDirectory() as d:
            for headers in [['description', 'description'], ['description', '']]:
                with self.assertRaises(ValueError):
                    profile(self.write_csv(d, [], headers=headers))
            with self.assertRaises(ValueError):
                profile(self.write_csv(d, [], metadata=['Hospital', '7/1/2026', 'lost value']))

    def test_payer_summary_fields_are_included(self):
        for header in ['standard_charge|Payer|PPO|negotiated_dollar', 'median_amount|Payer|PPO', 'additional_payer_notes|Payer|PPO']:
            self.assertEqual(payer_field(header)[:2], ('Payer', 'PPO'))
        self.assertIsNone(payer_field('standard_charge|gross'))


if __name__ == '__main__':
    unittest.main()
