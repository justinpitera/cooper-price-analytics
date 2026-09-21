# Data notes

[Back to the setup guide](../README.md)

## What's in the files?

Each CSV starts with two rows describing the hospital, then a row of column names. Each remaining row describes a service, with separate price columns for each insurance plan. The loader turns those many columns into tables that are easier to query.

These numbers describe the saved copies; future downloads may differ:

| | Cooper | Cape Regional |
| --- | ---: | ---: |
| File update date | June 23, 2026 | July 1, 2026 |
| Service rows | 25,654 | 13,702 |
| Insurance plan combinations | 42 | 37 |
| Service/plan rows with a dollar price | 27.43% | 27.43% |
| Repeated code/attribute combinations after the first occurrence | 1,143 | 2,439 |

There were no malformed or fully duplicated service rows. Repeated code combinations can still have different prices. The full [saved report](profile_summary.json) includes file fingerprints (SHA-256 hashes) so we can tell whether a download is the same version. The original download dates weren't recorded.

## The five tables

All tables are in `analytics`, a named group of tables inside the `cooper` database.

| Table | What one row means |
| --- | --- |
| `source_file` | One imported version of a CSV |
| `service` | One service row from that file |
| `service_code` | One of the service's three code slots, including empty slots |
| `payer_plan` | One insurance company (“payer”) and plan in that file |
| `service_rate` | One service and insurance plan, including entries with blank prices |

Join services using **both `source_file_id` and `csv_record`**. A procedure code alone isn't unique. `csv_record` counts CSV records, starting at 4 for the first service; a record may span several text lines.

Join plans using both `source_file_id` and the plan ID. When joining codes, select a slot (the first query uses slot 1) so each service's three code slots don't triple its prices.

Money uses exact decimal values. Blank numbers become SQL `NULL`; zero stays zero. Codes stay text so leading zeroes survive. A reported count of `1 through 10` stays a range, not a guessed number. These counts describe historical payment summaries, not total service volume.

The loader keeps the original cells and checks row counts and field totals against a fresh scan before saving each file. Reloading an identical file checks the existing import. A changed download is saved as a new snapshot, so keep `source_file_id` in your analysis to avoid mixing versions.

## What the first query does

[price_spread.sql](../sql/price_spread.sql) selects Cooper outpatient facility services with a primary CPT code. It excludes drug codes/units, uses positive dollar prices marked `fee schedule`, and excludes entries also expressed as percentages or formulas.

For each source service row with at least two eligible plans, it returns:

| Result | Meaning |
| --- | --- |
| `minimum_price`, `maximum_price` | Lowest and highest eligible plan prices |
| `price_spread` | Highest minus lowest, in dollars |
| `price_ratio` | Highest divided by lowest |
| `plan_count`, `payer_count` | Number of plans and distinct insurance companies |

Two plans can belong to the same insurer. A comparison between insurers needs at least two distinct payers.

**This is an exploration query.** It doesn't yet resolve repeated service definitions or review notes, modifiers, bundles, and units. Those details can make apparently similar prices incompatible. Historical median payment amounts are separate from negotiated prices and aren't used in this query.

## Finish the analysis in small steps

1. Read one query result and trace it back to the original CSV using its source file and record number.
2. Review notes, modifiers, and payment terms. Check repeated service definitions; flag unresolved rows and exclude them from final rankings. Inspect five large spreads and five ordinary examples.
3. Report coverage: how many services pass the filters, how many have two comparable plan prices, and how many each exclusion removes. A blank dollar price may have a percentage or formula instead; 27.43% is dollar availability, not an error rate.
4. Make one Metabase chart and a table of reviewed services. Write three findings supported by the query results, including which file versions you used and how much data you excluded.

Comparing hospitals and comparing negotiated prices with cash/gross charges can wait. Cross-hospital comparisons need verified one-to-one service matches and equivalent plans/payment terms. These files alone don't show patient savings, hospital profit, care quality, or which hospital is generally cheaper.
