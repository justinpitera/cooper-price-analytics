# Data notes

[Project overview and setup](../README.md)

## Source files

| | Cooper | Cape Regional |
| --- | ---: | ---: |
| File update date | June 23, 2026 | July 1, 2026 |
| Service records | 25,654 | 13,702 |
| Payer/plan combinations | 42 | 37 |
| Service/plan records with a dollar price | 27.43% | 27.43% |

These figures describe the saved files. New downloads may differ. The [saved profile](profile_summary.json) contains file hashes and detailed checks. No malformed or fully duplicated service rows were found; repeated procedure codes are present.

## Tables

All tables are in the `analytics` schema of the `cooper` database.

| Table | One row represents |
| --- | --- |
| `source_file` | An imported CSV version |
| `service` | A service record from that CSV |
| `service_code` | One of a service's three code slots |
| `payer_plan` | An insurer and plan within a source file |
| `service_rate` | A service/plan combination, including blank prices |

Join services on **`source_file_id` and `csv_record`**. A CPT code alone is not unique. Join plans on the source file and plan ID. The analysis uses code slot 1 to avoid counting each price more than once.

Blank numbers become `NULL`; zero stays zero. Codes remain text to preserve leading zeroes. Reported counts of `1 through 10` remain ranges. Changed files are stored as separate snapshots.

## Price comparisons

[price_spread.sql](../sql/price_spread.sql) selects Cooper outpatient facility records with a primary CPT code. It excludes drug codes and units, then keeps positive dollar prices marked `fee schedule` without an accompanying percentage or formula. Each service needs at least two eligible plan prices.

**Spread** is the highest price minus the lowest. **Ratio** is the highest divided by the lowest. Plan count and insurer count are separate: several plans may belong to one insurer.

[price_sensitivity.sql](../sql/price_sensitivity.sql) excludes rates with “lesser of” payer notes. It compares median spreads and ratios using only service records with at least two eligible prices in both versions. This keeps changes in the group of services from driving the comparison.

The sensitivity and detail queries use `source_file_id = 1`. That ID must refer to the intended Cooper snapshot.

## Interpretation

Payment notes, modifiers, bundles, and units can affect comparability. Excluding one type of payment note does not resolve every difference. Blank dollar prices may instead have percentage or formula terms.

Published negotiated prices are not patient bills or historical payment amounts. This analysis does not measure patient savings, hospital profit, care quality, or differences between hospitals.
