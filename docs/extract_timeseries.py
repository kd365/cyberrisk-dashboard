#!/usr/bin/env python3
"""
Coresignal Company Data Extractor
Extracts time-series employee metrics for cybersecurity company analysis.
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime

def load_company_data(filepath: str) -> dict:
    """Load and return company JSON data."""
    with open(filepath) as f:
        return json.load(f)

def parse_date(date_str: str) -> pd.Timestamp:
    """Parse date string in either YYYY-MM-DD or YYYYMM format."""
    if len(date_str) == 6:  # YYYYMM format
        return pd.to_datetime(date_str + '01', format='%Y%m%d')
    return pd.to_datetime(date_str)

def extract_monthly_headcount(data: dict) -> pd.DataFrame:
    """Extract monthly employee count time series."""
    records = data.get('employees_count_by_month', [])
    if not records:
        return pd.DataFrame()
    
    df = pd.DataFrame(records)
    df['date'] = df['date'].apply(parse_date)
    df['company'] = data['company_name']
    df['ticker'] = data['stock_ticker'][0]['ticker'] if data.get('stock_ticker') else None
    return df[['company', 'ticker', 'date', 'employees_count']].sort_values('date')

def extract_hires_departures(data: dict) -> pd.DataFrame:
    """Extract monthly hires and departures."""
    hires = data.get('employees_hired_by_month', [])
    left = data.get('employees_left_by_month', [])
    
    if not hires and not left:
        return pd.DataFrame()
    
    hires_df = pd.DataFrame(hires) if hires else pd.DataFrame(columns=['date', 'employees_hired_count'])
    left_df = pd.DataFrame(left) if left else pd.DataFrame(columns=['date', 'employees_left_count'])
    
    if not hires_df.empty:
        hires_df['date'] = hires_df['date'].apply(parse_date)
    if not left_df.empty:
        left_df['date'] = left_df['date'].apply(parse_date)
    
    df = pd.merge(hires_df, left_df, on='date', how='outer').fillna(0)
    df['company'] = data['company_name']
    df['net_change'] = df['employees_hired_count'] - df['employees_left_count']
    
    cols = ['company', 'date', 'employees_hired_count', 'employees_left_count', 'net_change']
    return df[cols].sort_values('date')

def extract_by_department(data: dict) -> pd.DataFrame:
    """Extract employee count by department over time."""
    records = data.get('employees_count_breakdown_by_department_by_month', [])
    if not records:
        return pd.DataFrame()
    
    rows = []
    for record in records:
        date = record.get('date')
        breakdown = record.get('employees_count_breakdown_by_department', {})
        for key, value in breakdown.items():
            if value is not None:
                dept = key.replace('employees_count_', '')
                rows.append({
                    'company': data['company_name'],
                    'date': date,
                    'department': dept,
                    'count': value
                })
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df['date'] = df['date'].apply(parse_date)
    return df.sort_values(['date', 'department'])

def extract_by_country(data: dict) -> pd.DataFrame:
    """Extract employee count by country over time."""
    records = data.get('employees_count_by_country_by_month', [])
    if not records:
        return pd.DataFrame()
    
    rows = []
    for record in records:
        date = record.get('date')
        countries = record.get('employees_count_by_country', [])
        for item in countries:
            rows.append({
                'company': data['company_name'],
                'date': date,
                'country': item['country'],
                'count': item['employee_count']
            })
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df['date'] = df['date'].apply(parse_date)
    return df.sort_values(['date', 'country'])

def extract_by_seniority(data: dict) -> pd.DataFrame:
    """Extract employee count by seniority level over time."""
    records = data.get('employees_count_breakdown_by_seniority_by_month', [])
    if not records:
        return pd.DataFrame()
    
    rows = []
    for record in records:
        date = record.get('date')
        breakdown = record.get('employees_count_breakdown_by_seniority', {})
        for key, value in breakdown.items():
            if value is not None:
                level = key.replace('employees_count_', '')
                rows.append({
                    'company': data['company_name'],
                    'date': date,
                    'seniority': level,
                    'count': value
                })
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df['date'] = df['date'].apply(parse_date)
    return df.sort_values(['date', 'seniority'])

def extract_by_region(data: dict) -> pd.DataFrame:
    """Extract employee count by region over time."""
    records = data.get('employees_count_breakdown_by_region_by_month', [])
    if not records:
        return pd.DataFrame()
    
    rows = []
    for record in records:
        date = record.get('date')
        breakdown = record.get('employees_count_breakdown_by_region', {})
        for key, value in breakdown.items():
            if value is not None:
                region = key.replace('employees_count_', '')
                rows.append({
                    'company': data['company_name'],
                    'date': date,
                    'region': region,
                    'count': value
                })
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df['date'] = df['date'].apply(parse_date)
    return df.sort_values(['date', 'region'])

def extract_company_summary(data: dict) -> dict:
    """Extract key company metadata."""
    return {
        'id': data.get('id'),
        'company_name': data.get('company_name'),
        'legal_name': data.get('company_legal_name'),
        'ticker': data['stock_ticker'][0]['ticker'] if data.get('stock_ticker') else None,
        'exchange': next((t['exchange'] for t in data.get('stock_ticker', []) if t.get('exchange')), None),
        'website': data.get('website'),
        'linkedin_url': data.get('linkedin_url'),
        'industry': data.get('industry'),
        'employees_count_current': data.get('employees_count'),
        'followers_linkedin': data.get('followers_count_linkedin'),
        'hq_location': data.get('hq_location'),
        'hq_country': data.get('hq_country'),
        'founded_year': data.get('founded_year'),
        'size_range': data.get('size_range'),
        'last_updated': data.get('last_updated_at')
    }

def process_all_companies(filepaths: list) -> dict:
    """Process all company files and return consolidated DataFrames."""
    
    headcount_dfs = []
    flow_dfs = []
    dept_dfs = []
    country_dfs = []
    seniority_dfs = []
    region_dfs = []
    summaries = []
    
    for fp in filepaths:
        print(f"Processing: {fp}")
        data = load_company_data(fp)
        
        summaries.append(extract_company_summary(data))
        
        hc = extract_monthly_headcount(data)
        if not hc.empty:
            headcount_dfs.append(hc)
        
        flow = extract_hires_departures(data)
        if not flow.empty:
            flow_dfs.append(flow)
        
        dept = extract_by_department(data)
        if not dept.empty:
            dept_dfs.append(dept)
        
        country = extract_by_country(data)
        if not country.empty:
            country_dfs.append(country)
        
        seniority = extract_by_seniority(data)
        if not seniority.empty:
            seniority_dfs.append(seniority)
        
        region = extract_by_region(data)
        if not region.empty:
            region_dfs.append(region)
    
    return {
        'summary': pd.DataFrame(summaries),
        'headcount': pd.concat(headcount_dfs, ignore_index=True) if headcount_dfs else pd.DataFrame(),
        'employee_flow': pd.concat(flow_dfs, ignore_index=True) if flow_dfs else pd.DataFrame(),
        'by_department': pd.concat(dept_dfs, ignore_index=True) if dept_dfs else pd.DataFrame(),
        'by_country': pd.concat(country_dfs, ignore_index=True) if country_dfs else pd.DataFrame(),
        'by_seniority': pd.concat(seniority_dfs, ignore_index=True) if seniority_dfs else pd.DataFrame(),
        'by_region': pd.concat(region_dfs, ignore_index=True) if region_dfs else pd.DataFrame()
    }

def main():
    # Input files - use local paths relative to script location
    script_dir = Path(__file__).parent
    files = [
        script_dir / 'crowdstrike.json',
        script_dir / 'zscaler.json',
        script_dir / 'cloudflare.json',
    ]

    # Filter to existing files only
    files = [f for f in files if f.exists()]

    if not files:
        print("No company JSON files found in docs directory")
        return

    # Process all companies
    results = process_all_companies([str(f) for f in files])

    # Output directory
    output_dir = script_dir / 'output'
    output_dir.mkdir(exist_ok=True)
    
    # Save to CSV
    for name, df in results.items():
        if not df.empty:
            outpath = output_dir / f'{name}.csv'
            df.to_csv(outpath, index=False)
            print(f"Saved: {outpath} ({len(df)} rows)")
    
    # Print summary
    print("\n" + "="*60)
    print("COMPANY SUMMARY")
    print("="*60)
    print(results['summary'][['company_name', 'ticker', 'employees_count_current', 'industry']].to_string(index=False))
    
    print("\n" + "="*60)
    print("HEADCOUNT DATE RANGES")
    print("="*60)
    if not results['headcount'].empty:
        for company in results['headcount']['company'].unique():
            subset = results['headcount'][results['headcount']['company'] == company]
            print(f"{company}: {subset['date'].min().date()} to {subset['date'].max().date()} ({len(subset)} months)")
    
    print("\n" + "="*60)
    print("LATEST HEADCOUNT COMPARISON")
    print("="*60)
    if not results['headcount'].empty:
        latest = results['headcount'].sort_values('date').groupby('company').tail(1)
        print(latest[['company', 'ticker', 'date', 'employees_count']].to_string(index=False))

if __name__ == '__main__':
    main()
