-- Compare plan prices for the same Cooper outpatient service.
-- Run in the cooper database after loading the CSVs.
-- Before presenting findings, review notes, modifiers, units,
-- and repeated service definitions. See docs/data_notes.md.
WITH
    eligible_prices AS (
        -- Step 1: Select the services and prices we want to compare.
        SELECT
            services.source_file_id,
            services.csv_record,
            services.description,
            codes.code AS cpt_code,
            plans.payer,
            plans.plan,
            rates.negotiated_dollar
        FROM
            analytics.service AS services
            JOIN analytics.source_file AS files ON files.id = services.source_file_id
            -- Use only the primary code so extra code slots don't repeat prices.
            JOIN analytics.service_code AS codes ON codes.source_file_id = services.source_file_id
            AND codes.csv_record = services.csv_record
            AND codes.slot = 1
            JOIN analytics.service_rate AS rates ON rates.source_file_id = services.source_file_id
            AND rates.csv_record = services.csv_record
            JOIN analytics.payer_plan AS plans ON plans.source_file_id = rates.source_file_id
            AND plans.id = rates.payer_plan_id
        WHERE
            -- ->> reads the hospital name from the file's JSON metadata.
            files.metadata - > > 'hospital_name' = 'Cooper University Hospital'
            -- Include outpatient facility services with a primary CPT code.
            AND services.setting = 'outpatient'
            AND services.billing_class = 'facility'
            AND codes.code_type = 'CPT'
            AND codes.code <> ''
            -- Exclude services with drug measurement information.
            AND services.drug_unit_of_measurement IS NULL
            AND services.drug_type_of_measurement = ''
            -- Also exclude services with a nonempty NDC drug code in any slot.
            -- NOT EXISTS means no matching drug-code row can be found.
            AND NOT EXISTS (
                SELECT
                    1
                FROM
                    analytics.service_code AS drug_codes
                WHERE
                    drug_codes.source_file_id = services.source_file_id
                    AND drug_codes.csv_record = services.csv_record
                    AND drug_codes.code_type = 'NDC'
                    AND drug_codes.code <> ''
            )
            -- Include only positive dollar prices using a fee schedule.
            -- LOWER and TRIM ignore capitalization and surrounding spaces.
            AND rates.negotiated_dollar > 0
            AND LOWER(TRIM(rates.methodology)) = 'fee schedule'
            -- Exclude prices that also specify a percentage or algorithm.
            AND rates.negotiated_percentage IS NULL
            AND rates.negotiated_algorithm = ''
    ),
    service_price_summary AS (
        -- Step 2: Find the lowest and highest eligible price for each service row.
        SELECT
            source_file_id,
            csv_record,
            description,
            cpt_code,
            MIN(negotiated_dollar) AS minimum_price,
            MAX(negotiated_dollar) AS maximum_price,
            COUNT(*) AS plan_count,
            COUNT(DISTINCT payer) AS payer_count
        FROM
            eligible_prices
            -- Keep separate source rows and file versions separate,
            -- even when they have the same CPT code.
        GROUP BY
            source_file_id,
            csv_record,
            description,
            cpt_code
            -- We need at least two eligible price rows to compare.
        HAVING
            COUNT(*) >= 2
    )
    -- Step 3: Calculate the price differences and show the largest spread first.
SELECT
    source_file_id,
    csv_record,
    description,
    cpt_code,
    minimum_price,
    maximum_price,
    -- Dollar difference between the highest and lowest price.
    maximum_price - minimum_price AS price_spread,
    -- How many times the lowest price fits into the highest.
    -- For example, 3 means the highest price is 3 times the lowest.
    maximum_price / minimum_price AS price_ratio,
    plan_count,
    payer_count
FROM
    service_price_summary
ORDER BY
    price_spread DESC;