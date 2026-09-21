-- Setup file: Docker runs this on a fresh database, and the loader runs it too.
-- IF NOT EXISTS lets it run again without replacing tables or deleting data.
CREATE SCHEMA IF NOT EXISTS analytics;
COMMENT ON SCHEMA analytics IS 'Hospital price analysis; Metabase application data uses a separate database.';

-- One row per downloaded file version. The hash prevents duplicate imports.
CREATE TABLE IF NOT EXISTS analytics.source_file (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha256 text NOT NULL UNIQUE CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    filename text NOT NULL,
    source_url text,
    downloaded_at timestamptz,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    metadata jsonb NOT NULL,
    last_updated_on date NOT NULL,
    template_version text NOT NULL,
    headers text[] NOT NULL,
    audit jsonb NOT NULL
);

-- One row per service in the CSV. Codes can repeat, so identify a service by
-- its source file and CSV record number instead of its procedure code.
CREATE TABLE IF NOT EXISTS analytics.service (
    source_file_id bigint NOT NULL REFERENCES analytics.source_file(id),
    csv_record integer NOT NULL CHECK (csv_record >= 4),
    description text NOT NULL,
    setting text NOT NULL,
    billing_class text NOT NULL,
    modifiers text NOT NULL,
    drug_unit_of_measurement numeric,
    drug_type_of_measurement text NOT NULL,
    gross numeric,
    discounted_cash numeric,
    published_min numeric,
    published_max numeric,
    additional_generic_notes text NOT NULL,
    -- Original cells, in source_file.headers order, preserve every source string.
    raw_values text[] NOT NULL,
    PRIMARY KEY (source_file_id, csv_record)
);

-- Each service has three code slots. Codes are text to keep leading zeroes.
CREATE TABLE IF NOT EXISTS analytics.service_code (
    source_file_id bigint NOT NULL,
    csv_record integer NOT NULL,
    slot smallint NOT NULL CHECK (slot BETWEEN 1 AND 3),
    code text NOT NULL,
    code_type text NOT NULL,
    PRIMARY KEY (source_file_id, csv_record, slot),
    FOREIGN KEY (source_file_id, csv_record)
        REFERENCES analytics.service(source_file_id, csv_record)
);

-- A payer is an insurance company; each company may have several plans.
-- Plan IDs belong to one source file, so joins need source_file_id as well.
CREATE TABLE IF NOT EXISTS analytics.payer_plan (
    source_file_id bigint NOT NULL REFERENCES analytics.source_file(id),
    id integer NOT NULL CHECK (id > 0),
    payer text NOT NULL,
    plan text NOT NULL,
    PRIMARY KEY (source_file_id, id),
    UNIQUE (source_file_id, payer, plan)
);

-- One row per service and plan, even when its price is blank (NULL).
-- Dollar prices, percentages, and historical payment summaries stay separate.
CREATE TABLE IF NOT EXISTS analytics.service_rate (
    source_file_id bigint NOT NULL,
    csv_record integer NOT NULL,
    payer_plan_id integer NOT NULL,
    negotiated_dollar numeric,
    negotiated_percentage numeric,
    negotiated_algorithm text NOT NULL,
    methodology text NOT NULL,
    median_amount numeric,
    percentile_10 numeric,
    percentile_90 numeric,
    count_raw text NOT NULL,
    count_exact bigint,
    count_lower bigint,
    count_upper bigint,
    additional_payer_notes text NOT NULL,
    PRIMARY KEY (source_file_id, csv_record, payer_plan_id),
    FOREIGN KEY (source_file_id, csv_record)
        REFERENCES analytics.service(source_file_id, csv_record),
    FOREIGN KEY (source_file_id, payer_plan_id)
        REFERENCES analytics.payer_plan(source_file_id, id),
    -- The source reports counts as blank, 0, an exact count >= 11, or 1 through 10.
    CHECK (
        (count_exact IS NULL AND count_lower IS NULL AND count_upper IS NULL)
        OR (count_exact IS NOT NULL AND (count_exact = 0 OR count_exact >= 11)
            AND count_lower IS NULL AND count_upper IS NULL)
        OR (count_exact IS NULL AND count_lower IS NOT NULL AND count_upper IS NOT NULL
            AND count_lower = 1 AND count_upper = 10)
    )
);

CREATE INDEX IF NOT EXISTS service_rate_plan_idx
    ON analytics.service_rate(source_file_id, payer_plan_id);
