-- =============================================================================
-- Add Taxonomy Columns to Companies Table
-- =============================================================================
-- This migration adds cybersecurity classification fields to the companies table
-- so taxonomy data lives in the database rather than being hardcoded.
--
-- Run with: psql -h <host> -U <user> -d cyberrisk -f add_taxonomy_columns.sql
-- =============================================================================

-- Add new taxonomy columns
ALTER TABLE companies ADD COLUMN IF NOT EXISTS cyber_sector VARCHAR(50);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS cyber_focus TEXT[];  -- Array of focus areas
ALTER TABLE companies ADD COLUMN IF NOT EXISTS gics_sector VARCHAR(100);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS gics_industry VARCHAR(100);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS gics_sub_industry_code VARCHAR(20);

-- These columns may already exist but ensure they're available
-- (The original schema had some of these)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS exchange VARCHAR(20);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS location VARCHAR(255);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS domain VARCHAR(255);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS alternate_names JSONB;  -- Array of aliases for entity resolution

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_companies_cyber_sector ON companies(cyber_sector);
CREATE INDEX IF NOT EXISTS idx_companies_exchange ON companies(exchange);

-- Add comments for documentation
COMMENT ON COLUMN companies.cyber_sector IS 'Cybersecurity market segment: endpoint_security, network_security, cloud_security, identity_access, security_operations, application_security, data_security, email_security, vulnerability_management, managed_security';
COMMENT ON COLUMN companies.cyber_focus IS 'Array of specific technology focus areas like EDR, XDR, SIEM, etc.';
COMMENT ON COLUMN companies.gics_sector IS 'GICS Sector classification (e.g., Information Technology)';
COMMENT ON COLUMN companies.gics_industry IS 'GICS Industry classification (e.g., Systems Software)';
COMMENT ON COLUMN companies.gics_sub_industry_code IS 'GICS Sub-Industry code (e.g., 45103020)';
COMMENT ON COLUMN companies.exchange IS 'Stock exchange (NYSE, NASDAQ, etc.)';
COMMENT ON COLUMN companies.location IS 'Company headquarters location';
COMMENT ON COLUMN companies.domain IS 'Company website domain for lookups';
COMMENT ON COLUMN companies.alternate_names IS 'JSON array of aliases for entity resolution (e.g., ["Palo Alto", "PANW"])';

-- Verify the changes
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'companies'
ORDER BY ordinal_position;
