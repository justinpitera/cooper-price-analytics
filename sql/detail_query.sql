SELECT
    plans.payer,
    plans.plan,
    rates.negotiated_dollar AS price
FROM
    analytics.service_rate AS rates
    JOIN analytics.payer_plan AS plans ON plans.source_file_id = rates.source_file_id
    AND plans.id = rates.payer_plan_id
WHERE
    rates.source_file_id = 1
    AND rates.csv_record = 1469
    AND rates.negotiated_dollar > 0
    AND LOWER(TRIM(rates.methodology)) = 'fee schedule'
    AND rates.negotiated_percentage IS NULL
    AND rates.negotiated_algorithm = ''
ORDER BY
    price;