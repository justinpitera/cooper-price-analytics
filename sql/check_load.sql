-- Run after loading the CSV files.
-- Each actual row count should match its expected row count.

WITH expected_counts AS (
    -- Read the expected counts from each file's saved import report.
    SELECT
        id,
        filename,
        sha256,
        (audit->'quality'->>'total_records')::bigint AS service_rows,
        jsonb_array_length(audit->'payer_plans') AS plan_rows
    FROM analytics.source_file
),

-- Count each table separately so joins don't inflate the counts.
service_counts AS (
    SELECT
        source_file_id,
        COUNT(*) AS service_rows
    FROM analytics.service
    GROUP BY source_file_id
),

code_counts AS (
    SELECT
        source_file_id,
        COUNT(*) AS code_rows
    FROM analytics.service_code
    GROUP BY source_file_id
),

plan_counts AS (
    SELECT
        source_file_id,
        COUNT(*) AS plan_rows
    FROM analytics.payer_plan
    GROUP BY source_file_id
),

rate_counts AS (
    SELECT
        source_file_id,
        COUNT(*) AS rate_rows,

        -- Populated means any non-NULL amount, including zero.
        COUNT(*) FILTER (
            WHERE negotiated_dollar IS NOT NULL
        ) AS dollar_populated,

        COUNT(*) FILTER (
            WHERE negotiated_dollar IS NULL
        ) AS dollar_blank,

        -- Zero prices are already included in dollar_populated.
        COUNT(*) FILTER (
            WHERE negotiated_dollar = 0
        ) AS dollar_zero,

        -- Count records whose count is reported as a range of 1–10.
        COUNT(*) FILTER (
            WHERE count_lower = 1 AND count_upper = 10
        ) AS suppressed_counts

    FROM analytics.service_rate
    GROUP BY source_file_id
)

-- Show actual and expected counts side by side for each file.
SELECT
    expected.id,
    expected.filename,
    expected.sha256,

    -- COALESCE displays 0 when no matching rows were loaded.
    COALESCE(services.service_rows, 0) AS service_rows,
    expected.service_rows AS expected_service_rows,

    -- Assumes the loader saves all 3 code slots for each service.
    COALESCE(codes.code_rows, 0) AS code_rows,
    expected.service_rows * 3 AS expected_code_rows,

    COALESCE(plans.plan_rows, 0) AS plan_rows,
    expected.plan_rows AS expected_plan_rows,

    -- Assumes one rate row for every service and payer-plan combination.
    COALESCE(rates.rate_rows, 0) AS rate_rows,
    expected.service_rows * expected.plan_rows AS expected_rate_rows,

    COALESCE(rates.dollar_populated, 0) AS dollar_populated,
    COALESCE(rates.dollar_blank, 0) AS dollar_blank,
    COALESCE(rates.dollar_zero, 0) AS dollar_zero,
    COALESCE(rates.suppressed_counts, 0) AS suppressed_counts

FROM expected_counts AS expected

-- LEFT JOIN keeps each source file visible even if a table has no rows.
LEFT JOIN service_counts AS services
    ON services.source_file_id = expected.id

LEFT JOIN code_counts AS codes
    ON codes.source_file_id = expected.id

LEFT JOIN plan_counts AS plans
    ON plans.source_file_id = expected.id

LEFT JOIN rate_counts AS rates
    ON rates.source_file_id = expected.id

ORDER BY expected.id;