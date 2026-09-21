-- Loaded into metabase
WITH eligible_prices AS (
    -- Select the same services and prices as your original analysis.
    SELECT
        services.source_file_id,
        services.csv_record,
        rates.negotiated_dollar AS price,
        COALESCE(rates.additional_payer_notes, '')
            ILIKE '%lesser of%' AS has_lesser_of_note
    FROM analytics.service AS services
    JOIN analytics.source_file AS files
        ON files.id = services.source_file_id
    JOIN analytics.service_code AS codes
        ON codes.source_file_id = services.source_file_id
        AND codes.csv_record = services.csv_record
        AND codes.slot = 1
    JOIN analytics.service_rate AS rates
        ON rates.source_file_id = services.source_file_id
        AND rates.csv_record = services.csv_record
    JOIN analytics.payer_plan AS plans
        ON plans.source_file_id = rates.source_file_id
        AND plans.id = rates.payer_plan_id
    WHERE services.source_file_id = 1
        AND files.metadata->>'hospital_name' = 'Cooper University Hospital'
        AND services.setting = 'outpatient'
        AND services.billing_class = 'facility'
        AND codes.code_type = 'CPT'
        AND codes.code <> ''
        AND services.drug_unit_of_measurement IS NULL
        AND services.drug_type_of_measurement = ''
        AND NOT EXISTS (
            SELECT 1
            FROM analytics.service_code AS drug_codes
            WHERE drug_codes.source_file_id = services.source_file_id
                AND drug_codes.csv_record = services.csv_record
                AND drug_codes.code_type = 'NDC'
                AND drug_codes.code <> ''
        )
        AND rates.negotiated_dollar > 0
        AND LOWER(TRIM(rates.methodology)) = 'fee schedule'
        AND rates.negotiated_percentage IS NULL
        AND rates.negotiated_algorithm = ''
),
service_summary AS (
    -- Calculate each service's prices before and after the exclusion.
    SELECT
        source_file_id,
        csv_record,
        COUNT(*) AS original_count,
        MIN(price) AS original_min,
        MAX(price) AS original_max,

        COUNT(*) FILTER (
            WHERE NOT has_lesser_of_note
        ) AS remaining_count,
        MIN(price) FILTER (
            WHERE NOT has_lesser_of_note
        ) AS remaining_min,
        MAX(price) FILTER (
            WHERE NOT has_lesser_of_note
        ) AS remaining_max
    FROM eligible_prices
    GROUP BY source_file_id, csv_record
    HAVING COUNT(*) >= 2
),
comparisons AS (
    SELECT
        *,
        original_max - original_min AS original_spread,
        original_max / NULLIF(original_min, 0) AS original_ratio,
        remaining_max - remaining_min AS remaining_spread,
        remaining_max / NULLIF(remaining_min, 0) AS remaining_ratio
    FROM service_summary
)

-- Compare typical values using ONLY services eligible in both versions.
SELECT
    '1. Original filters' AS version,
    COUNT(*) AS eligible_services,
    0::bigint AS services_lost,
    COUNT(*) FILTER (
        WHERE remaining_count >= 2
    ) AS matched_services,
    ROUND(
        (PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY original_spread
        ) FILTER (WHERE remaining_count >= 2))::numeric,
        2
    ) AS median_spread_matched,
    ROUND(
        (PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY original_ratio
        ) FILTER (WHERE remaining_count >= 2))::numeric,
        2
    ) AS median_ratio_matched
FROM comparisons

UNION ALL

SELECT
    '2. Excluding lesser-of rates' AS version,
    COUNT(*) FILTER (
        WHERE remaining_count >= 2
    ) AS eligible_services,
    COUNT(*) FILTER (
        WHERE remaining_count < 2
    ) AS services_lost,
    COUNT(*) FILTER (
        WHERE remaining_count >= 2
    ) AS matched_services,
    ROUND(
        (PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY remaining_spread
        ) FILTER (WHERE remaining_count >= 2))::numeric,
        2
    ) AS median_spread_matched,
    ROUND(
        (PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY remaining_ratio
        ) FILTER (WHERE remaining_count >= 2))::numeric,
        2
    ) AS median_ratio_matched
FROM comparisons
ORDER BY version;