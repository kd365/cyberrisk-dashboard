#!/usr/bin/env python3
"""
Data Migration Script
Migrates data from S3 bucket (cyber-risk AWS profile) to RDS PostgreSQL (class AWS profile)

This script:
1. Reads company data, artifacts, and sentiment analysis from S3 CSV files
2. Creates the PostgreSQL schema if it doesn't exist
3. Migrates all data to RDS PostgreSQL

Usage:
    python migrate_data.py --s3-profile cyber-risk --db-profile class

Or with environment variables:
    export SOURCE_S3_BUCKET=cyber-risk-dashboard-data
    export DB_HOST=your-rds-endpoint.amazonaws.com
    export DB_NAME=cyberrisk
    export DB_USER=postgres
    export DB_PASSWORD=your-password
    python migrate_data.py
"""

import argparse
import os
import sys
import json
import csv
import io
from datetime import datetime
from typing import Dict, List, Optional

import boto3
import psycopg2
from psycopg2.extras import execute_values

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_S3_PROFILE = "cyber-risk"
DEFAULT_DB_PROFILE = "class"
DEFAULT_S3_BUCKET = "cyber-risk-dashboard-data"
DEFAULT_AWS_REGION = "us-east-1"

# Database schema
SCHEMA_SQL = """
-- =============================================================================
-- CORE COMPANY TABLES
-- =============================================================================

-- Companies table (primary company record)
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL UNIQUE,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    sector VARCHAR(100) DEFAULT 'Cybersecurity',
    domain VARCHAR(255),  -- Company website domain for Explorium lookups
    explorium_id VARCHAR(100),  -- Explorium business ID for API calls
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);

-- Company aliases (alternate names, misspellings, ticker variations)
-- Allows matching "crowdstrike", "CrowdStrike", "crowd strike", "CRWD" -> same company
CREATE TABLE IF NOT EXISTS company_aliases (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    alias VARCHAR(255) NOT NULL,
    alias_type VARCHAR(50) DEFAULT 'alternate_name',  -- 'ticker', 'alternate_name', 'misspelling', 'abbreviation'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(alias)
);

CREATE INDEX IF NOT EXISTS idx_company_aliases_alias ON company_aliases(LOWER(alias));
CREATE INDEX IF NOT EXISTS idx_company_aliases_company_id ON company_aliases(company_id);

-- =============================================================================
-- DOCUMENT/ARTIFACT TABLES
-- =============================================================================

-- Artifacts table (SEC filings, earnings calls, etc.)
CREATE TABLE IF NOT EXISTS artifacts (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    artifact_type VARCHAR(50) NOT NULL,  -- '10-K', '10-Q', '8-K', 'earnings_call', 'transcript'
    title VARCHAR(500),
    content TEXT,
    published_date DATE,
    fiscal_quarter VARCHAR(10),  -- 'Q1', 'Q2', 'Q3', 'Q4' for earnings calls
    fiscal_year INTEGER,
    source_url VARCHAR(1000),
    s3_key VARCHAR(500),  -- S3 object key for the document
    file_size_bytes BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, artifact_type, published_date, s3_key)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_company_id ON artifacts(company_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifacts_date ON artifacts(published_date);
CREATE INDEX IF NOT EXISTS idx_artifacts_company_type ON artifacts(company_id, artifact_type);

-- =============================================================================
-- CACHE TABLES (for persisting expensive computations)
-- =============================================================================

-- Sentiment analysis cache (stores full Comprehend analysis results as JSON)
CREATE TABLE IF NOT EXISTS sentiment_cache (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    artifact_hash VARCHAR(64) NOT NULL,
    sentiment_data JSONB NOT NULL,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, artifact_hash)
);

CREATE INDEX IF NOT EXISTS idx_sentiment_cache_ticker ON sentiment_cache(ticker);
CREATE INDEX IF NOT EXISTS idx_sentiment_cache_lookup ON sentiment_cache(ticker, artifact_hash);

-- Forecast cache (stores Prophet model predictions as JSON)
CREATE TABLE IF NOT EXISTS forecast_cache (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    forecast_days INT NOT NULL,
    forecast_data JSONB NOT NULL,
    model_metrics JSONB,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_forecast_cache_ticker ON forecast_cache(ticker);
CREATE INDEX IF NOT EXISTS idx_forecast_cache_lookup ON forecast_cache(ticker, forecast_days, computed_at);

-- =============================================================================
-- GROWTH METRICS TABLES (Explorium data)
-- =============================================================================

-- Employee count snapshots (historical tracking)
CREATE TABLE IF NOT EXISTS employee_counts (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    employee_count INTEGER,
    data_source VARCHAR(50) DEFAULT 'explorium',  -- 'explorium', 'sec_filing', 'manual'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, snapshot_date, data_source)
);

CREATE INDEX IF NOT EXISTS idx_employee_counts_company ON employee_counts(company_id, snapshot_date DESC);

-- Hiring events (job postings, new hires tracked over time)
CREATE TABLE IF NOT EXISTS hiring_events (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    event_date DATE NOT NULL,
    event_type VARCHAR(50) NOT NULL,  -- 'job_posting', 'new_hire', 'layoff', 'hiring_freeze'
    department VARCHAR(100),
    location VARCHAR(255),
    job_title VARCHAR(255),
    job_count INTEGER DEFAULT 1,  -- Number of positions
    description TEXT,
    source_url VARCHAR(1000),
    data_source VARCHAR(50) DEFAULT 'explorium',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hiring_events_company ON hiring_events(company_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_hiring_events_type ON hiring_events(event_type);

-- Growth trends (computed/cached trend analysis)
CREATE TABLE IF NOT EXISTS growth_trends (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    metric_type VARCHAR(50) NOT NULL,  -- 'employee_growth', 'hiring_velocity', 'overall'
    trend_classification VARCHAR(20) NOT NULL,  -- 'accelerating', 'stable', 'slowing', 'declining'
    trend_value FLOAT,  -- Percentage change or velocity score
    period_start DATE,
    period_end DATE,
    data_points INTEGER,  -- Number of data points used in calculation
    confidence_score FLOAT,  -- How confident in the trend (0-1)
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, metric_type, period_end)
);

CREATE INDEX IF NOT EXISTS idx_growth_trends_company ON growth_trends(company_id);
CREATE INDEX IF NOT EXISTS idx_growth_trends_classification ON growth_trends(trend_classification);

-- Growth cache (full Explorium API response cache)
CREATE TABLE IF NOT EXISTS growth_cache (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    cache_key VARCHAR(64) NOT NULL,  -- Hash of request parameters
    growth_data JSONB NOT NULL,  -- Full Explorium response
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,  -- When this cache entry should be refreshed
    UNIQUE(ticker, cache_key)
);

CREATE INDEX IF NOT EXISTS idx_growth_cache_ticker ON growth_cache(ticker);
CREATE INDEX IF NOT EXISTS idx_growth_cache_lookup ON growth_cache(ticker, cache_key);

-- =============================================================================
-- ANALYSIS TABLES
-- =============================================================================

-- Sentiment analysis results (per-artifact detailed results)
CREATE TABLE IF NOT EXISTS sentiment_analysis (
    id SERIAL PRIMARY KEY,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    sentiment VARCHAR(20) NOT NULL,  -- 'POSITIVE', 'NEGATIVE', 'NEUTRAL', 'MIXED'
    positive_score FLOAT,
    negative_score FLOAT,
    neutral_score FLOAT,
    mixed_score FLOAT,
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sentiment_artifact_id ON sentiment_analysis(artifact_id);

-- Key phrases extracted from documents
CREATE TABLE IF NOT EXISTS key_phrases (
    id SERIAL PRIMARY KEY,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    phrase VARCHAR(500) NOT NULL,
    score FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_keyphrases_artifact_id ON key_phrases(artifact_id);

-- =============================================================================
-- STOCK DATA TABLES
-- =============================================================================

-- Stock price history
CREATE TABLE IF NOT EXISTS stock_prices (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    price_date DATE NOT NULL,
    open_price FLOAT,
    high_price FLOAT,
    low_price FLOAT,
    close_price FLOAT,
    adj_close FLOAT,
    volume BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, price_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_prices_company_date ON stock_prices(company_id, price_date);

-- Forecast results (historical forecasts for analysis)
CREATE TABLE IF NOT EXISTS forecasts (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    forecast_date DATE NOT NULL,
    predicted_price FLOAT,
    yhat_lower FLOAT,
    yhat_upper FLOAT,
    trend FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_forecasts_company_date ON forecasts(company_id, forecast_date);

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to find company by any alias (ticker, name, misspelling)
CREATE OR REPLACE FUNCTION find_company_by_alias(search_term TEXT)
RETURNS TABLE(company_id INTEGER, ticker VARCHAR, company_name VARCHAR) AS $$
BEGIN
    RETURN QUERY
    SELECT c.id, c.ticker, c.company_name
    FROM companies c
    WHERE LOWER(c.ticker) = LOWER(search_term)
       OR LOWER(c.company_name) = LOWER(search_term)
    UNION
    SELECT c.id, c.ticker, c.company_name
    FROM companies c
    JOIN company_aliases ca ON c.id = ca.company_id
    WHERE LOWER(ca.alias) = LOWER(search_term)
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to get document inventory for a company
CREATE OR REPLACE FUNCTION get_document_inventory(company_ticker VARCHAR)
RETURNS TABLE(
    artifact_type VARCHAR,
    doc_count BIGINT,
    earliest_date DATE,
    latest_date DATE
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.artifact_type,
        COUNT(*) as doc_count,
        MIN(a.published_date) as earliest_date,
        MAX(a.published_date) as latest_date
    FROM artifacts a
    JOIN companies c ON a.company_id = c.id
    WHERE LOWER(c.ticker) = LOWER(company_ticker)
    GROUP BY a.artifact_type
    ORDER BY doc_count DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to calculate growth trend
CREATE OR REPLACE FUNCTION calculate_growth_trend(
    p_company_id INTEGER,
    p_metric_type VARCHAR,
    p_lookback_days INTEGER DEFAULT 90
)
RETURNS VARCHAR AS $$
DECLARE
    v_trend VARCHAR;
    v_growth_rate FLOAT;
    v_data_points INTEGER;
BEGIN
    -- Calculate growth rate based on employee counts
    IF p_metric_type = 'employee_growth' THEN
        SELECT
            CASE
                WHEN COUNT(*) < 2 THEN NULL
                ELSE (MAX(employee_count) - MIN(employee_count))::FLOAT / NULLIF(MIN(employee_count), 0) * 100
            END,
            COUNT(*)
        INTO v_growth_rate, v_data_points
        FROM employee_counts
        WHERE company_id = p_company_id
          AND snapshot_date >= CURRENT_DATE - p_lookback_days;

        IF v_growth_rate IS NULL OR v_data_points < 2 THEN
            v_trend := 'unknown';
        ELSIF v_growth_rate > 10 THEN
            v_trend := 'accelerating';
        ELSIF v_growth_rate > 0 THEN
            v_trend := 'stable';
        ELSIF v_growth_rate > -5 THEN
            v_trend := 'slowing';
        ELSE
            v_trend := 'declining';
        END IF;
    -- Calculate based on hiring events
    ELSIF p_metric_type = 'hiring_velocity' THEN
        SELECT COUNT(*)
        INTO v_data_points
        FROM hiring_events
        WHERE company_id = p_company_id
          AND event_date >= CURRENT_DATE - p_lookback_days
          AND event_type = 'job_posting';

        IF v_data_points > 50 THEN
            v_trend := 'accelerating';
        ELSIF v_data_points > 20 THEN
            v_trend := 'stable';
        ELSIF v_data_points > 5 THEN
            v_trend := 'slowing';
        ELSE
            v_trend := 'declining';
        END IF;
    ELSE
        v_trend := 'unknown';
    END IF;

    RETURN v_trend;
END;
$$ LANGUAGE plpgsql;
"""

# Companies to migrate with aliases and domains
COMPANIES = [
    {
        "name": "CrowdStrike Holdings",
        "ticker": "CRWD",
        "domain": "crowdstrike.com",
        "aliases": ["crowdstrike", "crowd strike", "crowd-strike", "CrowdStrike", "Crowdstrike"]
    },
    {
        "name": "Palo Alto Networks",
        "ticker": "PANW",
        "domain": "paloaltonetworks.com",
        "aliases": ["palo alto", "palo alto networks", "paloalto", "pan", "Palo Alto"]
    },
    {
        "name": "Fortinet Inc",
        "ticker": "FTNT",
        "domain": "fortinet.com",
        "aliases": ["fortinet", "Fortinet", "forti"]
    },
    {
        "name": "Zscaler Inc",
        "ticker": "ZS",
        "domain": "zscaler.com",
        "aliases": ["zscaler", "Zscaler", "z-scaler"]
    },
    {
        "name": "SentinelOne Inc",
        "ticker": "S",
        "domain": "sentinelone.com",
        "aliases": ["sentinelone", "sentinel one", "sentinel-one", "SentinelOne", "Sentinel One", "s1"]
    },
    {
        "name": "Microsoft Corporation",
        "ticker": "MSFT",
        "domain": "microsoft.com",
        "aliases": ["microsoft", "Microsoft", "msft", "MS"]
    },
    {
        "name": "Cisco Systems",
        "ticker": "CSCO",
        "domain": "cisco.com",
        "aliases": ["cisco", "Cisco", "cisco systems"]
    },
    {
        "name": "Okta Inc",
        "ticker": "OKTA",
        "domain": "okta.com",
        "aliases": ["okta", "Okta"]
    },
    {
        "name": "Cloudflare Inc",
        "ticker": "NET",
        "domain": "cloudflare.com",
        "aliases": ["cloudflare", "Cloudflare", "cloud flare"]
    },
    {
        "name": "CyberArk Software",
        "ticker": "CYBR",
        "domain": "cyberark.com",
        "aliases": ["cyberark", "CyberArk", "cyber ark"]
    },
    {
        "name": "Qualys Inc",
        "ticker": "QLYS",
        "domain": "qualys.com",
        "aliases": ["qualys", "Qualys"]
    },
]

# =============================================================================
# Helper Functions
# =============================================================================

def get_s3_client(profile_name: str, region: str = DEFAULT_AWS_REGION):
    """Create S3 client with specified profile"""
    session = boto3.Session(profile_name=profile_name, region_name=region)
    return session.client('s3')

def get_db_connection(host: str, database: str, user: str, password: str, port: int = 5432):
    """Create PostgreSQL database connection"""
    return psycopg2.connect(
        host=host,
        database=database,
        user=user,
        password=password,
        port=port
    )

def read_csv_from_s3(s3_client, bucket: str, key: str) -> List[Dict]:
    """Read CSV file from S3 and return as list of dicts"""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        return list(reader)
    except s3_client.exceptions.NoSuchKey:
        print(f"  Warning: File not found: s3://{bucket}/{key}")
        return []
    except Exception as e:
        print(f"  Error reading s3://{bucket}/{key}: {e}")
        return []

def read_json_from_s3(s3_client, bucket: str, key: str) -> Optional[Dict]:
    """Read JSON file from S3"""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        return json.loads(content)
    except s3_client.exceptions.NoSuchKey:
        print(f"  Warning: File not found: s3://{bucket}/{key}")
        return None
    except Exception as e:
        print(f"  Error reading s3://{bucket}/{key}: {e}")
        return None

def list_s3_objects(s3_client, bucket: str, prefix: str) -> List[str]:
    """List all objects in S3 with given prefix"""
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        keys = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if 'Contents' in page:
                keys.extend([obj['Key'] for obj in page['Contents']])
        return keys
    except Exception as e:
        print(f"  Error listing s3://{bucket}/{prefix}: {e}")
        return []

# =============================================================================
# Migration Functions
# =============================================================================

def create_schema(conn):
    """Create database schema"""
    print("Creating database schema...")
    cursor = conn.cursor()
    cursor.execute(SCHEMA_SQL)
    conn.commit()
    cursor.close()
    print("  Schema created successfully")

def migrate_companies(conn) -> Dict[str, int]:
    """Insert companies with aliases and return mapping of ticker to id"""
    print("Migrating companies...")
    cursor = conn.cursor()

    company_ids = {}
    for company in COMPANIES:
        # Insert or update company with domain
        cursor.execute("""
            INSERT INTO companies (company_name, ticker, domain)
            VALUES (%s, %s, %s)
            ON CONFLICT (ticker) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                domain = EXCLUDED.domain,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
        """, (company['name'], company['ticker'], company.get('domain')))
        company_id = cursor.fetchone()[0]
        company_ids[company['ticker']] = company_id
        print(f"  {company['name']} ({company['ticker']}) -> ID: {company_id}")

        # Insert aliases for this company
        aliases = company.get('aliases', [])
        for alias in aliases:
            try:
                cursor.execute("""
                    INSERT INTO company_aliases (company_id, alias, alias_type)
                    VALUES (%s, %s, 'alternate_name')
                    ON CONFLICT (alias) DO NOTHING
                """, (company_id, alias))
            except Exception as e:
                print(f"    Warning: Could not add alias '{alias}': {e}")

        # Also add ticker as an alias for easier matching
        try:
            cursor.execute("""
                INSERT INTO company_aliases (company_id, alias, alias_type)
                VALUES (%s, %s, 'ticker')
                ON CONFLICT (alias) DO NOTHING
            """, (company_id, company['ticker'].lower()))
        except Exception:
            pass

        print(f"    Added {len(aliases)} aliases")

    conn.commit()
    cursor.close()
    return company_ids

def migrate_artifacts(conn, s3_client, bucket: str, company_ids: Dict[str, int]) -> Dict[str, int]:
    """Migrate artifacts from S3 to PostgreSQL"""
    print("Migrating artifacts...")
    cursor = conn.cursor()
    artifact_ids = {}

    for ticker, company_id in company_ids.items():
        # Look for artifacts in various locations
        prefixes = [
            f"artifacts/{ticker}/",
            f"data/{ticker}/artifacts/",
            f"{ticker}/",
        ]

        for prefix in prefixes:
            keys = list_s3_objects(s3_client, bucket, prefix)
            for key in keys:
                if key.endswith('.json'):
                    artifact_data = read_json_from_s3(s3_client, bucket, key)
                    if artifact_data:
                        try:
                            cursor.execute("""
                                INSERT INTO artifacts
                                (company_id, artifact_type, title, content, published_date, source_url, file_path)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING
                                RETURNING id
                            """, (
                                company_id,
                                artifact_data.get('type', 'unknown'),
                                artifact_data.get('title', ''),
                                artifact_data.get('content', ''),
                                artifact_data.get('date'),
                                artifact_data.get('url', ''),
                                key
                            ))
                            result = cursor.fetchone()
                            if result:
                                artifact_ids[key] = result[0]
                        except Exception as e:
                            print(f"    Error inserting artifact {key}: {e}")

    # Also check for artifacts.csv
    artifacts_csv = read_csv_from_s3(s3_client, bucket, "artifacts.csv")
    if artifacts_csv:
        print(f"  Found artifacts.csv with {len(artifacts_csv)} records")
        for row in artifacts_csv:
            ticker = row.get('ticker', row.get('company_ticker', ''))
            if ticker in company_ids:
                try:
                    cursor.execute("""
                        INSERT INTO artifacts
                        (company_id, artifact_type, title, content, published_date, source_url, file_path)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING id
                    """, (
                        company_ids[ticker],
                        row.get('type', row.get('artifact_type', 'unknown')),
                        row.get('title', ''),
                        row.get('content', row.get('text', '')),
                        row.get('date', row.get('published_date')),
                        row.get('url', row.get('source_url', '')),
                        row.get('file_path', '')
                    ))
                    result = cursor.fetchone()
                    if result:
                        artifact_ids[row.get('id', row.get('file_path', ''))] = result[0]
                except Exception as e:
                    print(f"    Error inserting artifact from CSV: {e}")

    conn.commit()
    cursor.close()
    print(f"  Migrated {len(artifact_ids)} artifacts")
    return artifact_ids

def migrate_sentiment(conn, s3_client, bucket: str, company_ids: Dict[str, int]):
    """Migrate sentiment analysis results"""
    print("Migrating sentiment analysis...")
    cursor = conn.cursor()
    count = 0

    # Try sentiment.csv
    sentiment_csv = read_csv_from_s3(s3_client, bucket, "sentiment.csv")
    if not sentiment_csv:
        sentiment_csv = read_csv_from_s3(s3_client, bucket, "sentiment_analysis.csv")

    if sentiment_csv:
        print(f"  Found sentiment CSV with {len(sentiment_csv)} records")
        for row in sentiment_csv:
            try:
                # Get artifact_id by matching
                cursor.execute("""
                    SELECT a.id FROM artifacts a
                    JOIN companies c ON a.company_id = c.id
                    WHERE c.ticker = %s AND a.title LIKE %s
                    LIMIT 1
                """, (
                    row.get('ticker', ''),
                    f"%{row.get('title', row.get('artifact_title', ''))}%"
                ))
                result = cursor.fetchone()

                if result:
                    cursor.execute("""
                        INSERT INTO sentiment_analysis
                        (artifact_id, sentiment, positive_score, negative_score, neutral_score, mixed_score)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        result[0],
                        row.get('sentiment', 'NEUTRAL'),
                        float(row.get('positive', row.get('positive_score', 0)) or 0),
                        float(row.get('negative', row.get('negative_score', 0)) or 0),
                        float(row.get('neutral', row.get('neutral_score', 0)) or 0),
                        float(row.get('mixed', row.get('mixed_score', 0)) or 0)
                    ))
                    count += 1
            except Exception as e:
                print(f"    Error inserting sentiment: {e}")

    conn.commit()
    cursor.close()
    print(f"  Migrated {count} sentiment records")

def migrate_stock_prices(conn, s3_client, bucket: str, company_ids: Dict[str, int]):
    """Migrate stock price history"""
    print("Migrating stock prices...")
    cursor = conn.cursor()
    total_count = 0

    for ticker, company_id in company_ids.items():
        # Try various file names
        files_to_try = [
            f"stock_prices/{ticker}.csv",
            f"prices/{ticker}.csv",
            f"{ticker}_prices.csv",
            f"data/{ticker}/prices.csv"
        ]

        for file_key in files_to_try:
            prices = read_csv_from_s3(s3_client, bucket, file_key)
            if prices:
                print(f"  Found {len(prices)} price records for {ticker}")

                values = []
                for row in prices:
                    try:
                        values.append((
                            company_id,
                            row.get('date', row.get('Date')),
                            float(row.get('open', row.get('Open', 0)) or 0),
                            float(row.get('high', row.get('High', 0)) or 0),
                            float(row.get('low', row.get('Low', 0)) or 0),
                            float(row.get('close', row.get('Close', 0)) or 0),
                            float(row.get('adj_close', row.get('Adj Close', 0)) or 0),
                            int(float(row.get('volume', row.get('Volume', 0)) or 0))
                        ))
                    except (ValueError, TypeError) as e:
                        continue

                if values:
                    try:
                        execute_values(cursor, """
                            INSERT INTO stock_prices
                            (company_id, price_date, open_price, high_price, low_price,
                             close_price, adj_close, volume)
                            VALUES %s
                            ON CONFLICT (company_id, price_date) DO UPDATE SET
                                close_price = EXCLUDED.close_price,
                                adj_close = EXCLUDED.adj_close
                        """, values)
                        total_count += len(values)
                    except Exception as e:
                        print(f"    Error batch inserting prices: {e}")
                break

    conn.commit()
    cursor.close()
    print(f"  Migrated {total_count} price records")

def migrate_forecasts(conn, s3_client, bucket: str, company_ids: Dict[str, int]):
    """Migrate forecast data"""
    print("Migrating forecasts...")
    cursor = conn.cursor()
    total_count = 0

    for ticker, company_id in company_ids.items():
        files_to_try = [
            f"forecasts/{ticker}.csv",
            f"{ticker}_forecast.csv",
            f"data/{ticker}/forecast.csv"
        ]

        for file_key in files_to_try:
            forecasts = read_csv_from_s3(s3_client, bucket, file_key)
            if forecasts:
                print(f"  Found {len(forecasts)} forecast records for {ticker}")

                for row in forecasts:
                    try:
                        cursor.execute("""
                            INSERT INTO forecasts
                            (company_id, forecast_date, predicted_price, yhat_lower, yhat_upper, trend)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                        """, (
                            company_id,
                            row.get('ds', row.get('date')),
                            float(row.get('yhat', row.get('predicted', 0)) or 0),
                            float(row.get('yhat_lower', 0) or 0),
                            float(row.get('yhat_upper', 0) or 0),
                            float(row.get('trend', 0) or 0)
                        ))
                        total_count += 1
                    except Exception as e:
                        continue
                break

    conn.commit()
    cursor.close()
    print(f"  Migrated {total_count} forecast records")

# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Migrate data from S3 to RDS PostgreSQL')
    parser.add_argument('--s3-profile', default=os.environ.get('S3_PROFILE', DEFAULT_S3_PROFILE),
                        help='AWS profile for S3 access')
    parser.add_argument('--db-profile', default=os.environ.get('DB_PROFILE', DEFAULT_DB_PROFILE),
                        help='AWS profile for RDS access')
    parser.add_argument('--s3-bucket', default=os.environ.get('SOURCE_S3_BUCKET', DEFAULT_S3_BUCKET),
                        help='Source S3 bucket name')
    parser.add_argument('--db-host', default=os.environ.get('DB_HOST'),
                        help='RDS endpoint hostname')
    parser.add_argument('--db-name', default=os.environ.get('DB_NAME', 'cyberrisk'),
                        help='Database name')
    parser.add_argument('--db-user', default=os.environ.get('DB_USER', 'postgres'),
                        help='Database username')
    parser.add_argument('--db-password', default=os.environ.get('DB_PASSWORD'),
                        help='Database password')
    parser.add_argument('--region', default=os.environ.get('AWS_REGION', DEFAULT_AWS_REGION),
                        help='AWS region')

    args = parser.parse_args()

    # Validate required arguments
    if not args.db_host:
        print("Error: Database host is required. Use --db-host or set DB_HOST environment variable.")
        sys.exit(1)
    if not args.db_password:
        print("Error: Database password is required. Use --db-password or set DB_PASSWORD environment variable.")
        sys.exit(1)

    print("=" * 60)
    print("CyberRisk Data Migration")
    print("=" * 60)
    print(f"Source S3 Bucket: {args.s3_bucket} (profile: {args.s3_profile})")
    print(f"Target Database: {args.db_host}/{args.db_name}")
    print("=" * 60)

    try:
        # Initialize S3 client
        print("\nConnecting to S3...")
        s3_client = get_s3_client(args.s3_profile, args.region)

        # Initialize database connection
        print("Connecting to PostgreSQL...")
        conn = get_db_connection(
            host=args.db_host,
            database=args.db_name,
            user=args.db_user,
            password=args.db_password
        )
        print("  Connected successfully")

        # Run migrations
        print("\n" + "-" * 60)
        create_schema(conn)

        print("\n" + "-" * 60)
        company_ids = migrate_companies(conn)

        print("\n" + "-" * 60)
        artifact_ids = migrate_artifacts(conn, s3_client, args.s3_bucket, company_ids)

        print("\n" + "-" * 60)
        migrate_sentiment(conn, s3_client, args.s3_bucket, company_ids)

        print("\n" + "-" * 60)
        migrate_stock_prices(conn, s3_client, args.s3_bucket, company_ids)

        print("\n" + "-" * 60)
        migrate_forecasts(conn, s3_client, args.s3_bucket, company_ids)

        # Close connection
        conn.close()

        print("\n" + "=" * 60)
        print("Migration completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\nError during migration: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
