-- Keep future analysis tables separate from Metabase's application tables.
-- This namespace is organizational separation, not an access-control boundary.
CREATE SCHEMA IF NOT EXISTS analytics;
COMMENT ON SCHEMA analytics IS 'Hospital price analysis; public contains Metabase application data.';
