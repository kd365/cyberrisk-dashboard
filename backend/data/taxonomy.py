# =============================================================================
# CyberRisk Knowledge Graph Taxonomy
# =============================================================================
#
# This module defines the classification systems used in the knowledge graph:
# 1. GICS (Global Industry Classification Standard) - Financial standard
# 2. Cybersecurity Sector - Domain-specific classification
#
# =============================================================================

# -----------------------------------------------------------------------------
# GICS Classification (Global Industry Classification Standard)
# -----------------------------------------------------------------------------
# GICS is maintained by S&P and MSCI, widely used in financial analysis.
# Structure: Sector (2-digit) -> Industry Group (4-digit) -> Industry (6-digit) -> Sub-Industry (8-digit)

GICS_SECTORS = {
    "10": "Energy",
    "15": "Materials",
    "20": "Industrials",
    "25": "Consumer Discretionary",
    "30": "Consumer Staples",
    "35": "Health Care",
    "40": "Financials",
    "45": "Information Technology",
    "50": "Communication Services",
    "55": "Utilities",
    "60": "Real Estate",
}

# Relevant GICS Sub-Industries for cybersecurity companies
GICS_CYBER_RELEVANT = {
    "45103010": {
        "name": "Application Software",
        "description": "Companies that develop and license application software",
    },
    "45103020": {
        "name": "Systems Software",
        "description": "Companies that develop systems and infrastructure software",
    },
    "45102010": {
        "name": "IT Consulting & Other Services",
        "description": "IT consulting, managed services, and security services",
    },
}

# -----------------------------------------------------------------------------
# Cybersecurity Sector Classification (Domain-Specific)
# -----------------------------------------------------------------------------
# Custom taxonomy designed for cybersecurity investment analysis.
# Aligns with how the industry categorizes security solutions.

CYBER_SECTORS = {
    "endpoint_security": {
        "name": "Endpoint Security",
        "description": "Protection for endpoints including workstations, servers, and mobile devices. Includes EDR (Endpoint Detection & Response), XDR (Extended Detection & Response), antivirus, and endpoint protection platforms.",
        "examples": [
            "CrowdStrike",
            "SentinelOne",
            "Carbon Black",
            "Microsoft Defender",
        ],
        "key_capabilities": [
            "EDR",
            "XDR",
            "EPP",
            "Threat Intelligence",
            "Malware Prevention",
        ],
    },
    "network_security": {
        "name": "Network Security",
        "description": "Security solutions protecting network infrastructure. Includes firewalls, intrusion detection/prevention, network segmentation, and secure access.",
        "examples": ["Palo Alto Networks", "Fortinet", "Cisco", "Check Point"],
        "key_capabilities": [
            "NGFW",
            "IDS/IPS",
            "VPN",
            "SD-WAN Security",
            "Network Segmentation",
        ],
    },
    "cloud_security": {
        "name": "Cloud Security",
        "description": "Security for cloud environments and cloud-native applications. Includes CASB, CSPM, CWPP, and secure web gateways.",
        "examples": ["Zscaler", "Netskope", "Wiz", "Lacework"],
        "key_capabilities": [
            "CASB",
            "CSPM",
            "CWPP",
            "SASE",
            "Zero Trust Network Access",
        ],
    },
    "identity_access": {
        "name": "Identity & Access Management",
        "description": "Solutions for managing user identities, authentication, and authorization. Includes IAM, PAM, SSO, and MFA.",
        "examples": ["Okta", "CyberArk", "Ping Identity", "SailPoint"],
        "key_capabilities": ["IAM", "PAM", "SSO", "MFA", "Identity Governance"],
    },
    "security_operations": {
        "name": "Security Operations",
        "description": "Tools for security monitoring, analysis, and incident response. Includes SIEM, SOAR, threat intelligence platforms, and security analytics.",
        "examples": ["Splunk", "Elastic", "Sumo Logic", "Rapid7"],
        "key_capabilities": [
            "SIEM",
            "SOAR",
            "Threat Intelligence",
            "Log Management",
            "Security Analytics",
        ],
    },
    "application_security": {
        "name": "Application Security",
        "description": "Security testing and protection for applications. Includes SAST, DAST, SCA, API security, and DevSecOps tools.",
        "examples": ["Snyk", "Veracode", "Checkmarx", "Synopsys"],
        "key_capabilities": [
            "SAST",
            "DAST",
            "SCA",
            "API Security",
            "Container Security",
        ],
    },
    "data_security": {
        "name": "Data Security",
        "description": "Protection and governance of data. Includes DLP, encryption, data classification, backup, and privacy management.",
        "examples": ["Varonis", "Rubrik", "Cohesity", "BigID"],
        "key_capabilities": [
            "DLP",
            "Encryption",
            "Data Classification",
            "Backup & Recovery",
            "Privacy",
        ],
    },
    "email_security": {
        "name": "Email & Collaboration Security",
        "description": "Security for email and collaboration platforms. Includes email gateways, phishing protection, and secure file sharing.",
        "examples": ["Proofpoint", "Mimecast", "Abnormal Security"],
        "key_capabilities": [
            "Email Gateway",
            "Phishing Protection",
            "BEC Prevention",
            "DMARC",
        ],
    },
    "vulnerability_management": {
        "name": "Vulnerability Management",
        "description": "Discovery and remediation of security vulnerabilities. Includes vulnerability scanning, penetration testing, and attack surface management.",
        "examples": ["Tenable", "Qualys", "Rapid7", "CrowdStrike Falcon Surface"],
        "key_capabilities": [
            "Vulnerability Scanning",
            "Pen Testing",
            "ASM",
            "Risk Prioritization",
        ],
    },
    "managed_security": {
        "name": "Managed Security Services",
        "description": "Outsourced security operations and monitoring. Includes MSSP, MDR, and security consulting services.",
        "examples": ["Secureworks", "Arctic Wolf", "Expel", "Red Canary"],
        "key_capabilities": ["MDR", "MSSP", "Incident Response", "Security Consulting"],
    },
}

# -----------------------------------------------------------------------------
# Tracked Company Mappings
# -----------------------------------------------------------------------------
# Classification for companies tracked in the CyberRisk dashboard

TRACKED_COMPANIES = {
    "CRWD": {
        "name": "CrowdStrike Holdings",
        "ticker": "CRWD",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "endpoint_security",
        "cyber_focus": [
            "EDR",
            "XDR",
            "Threat Intelligence",
            "Cloud Workload Protection",
        ],
        "description": "Cloud-native endpoint and workload protection platform",
    },
    "PANW": {
        "name": "Palo Alto Networks",
        "ticker": "PANW",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "network_security",
        "cyber_focus": ["NGFW", "SASE", "Cloud Security", "SOC"],
        "description": "Comprehensive cybersecurity platform spanning network, cloud, and SOC",
    },
    "ZS": {
        "name": "Zscaler",
        "ticker": "ZS",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "cloud_security",
        "cyber_focus": ["SASE", "Zero Trust", "SWG", "CASB"],
        "description": "Cloud security platform enabling zero trust network access",
    },
    "FTNT": {
        "name": "Fortinet",
        "ticker": "FTNT",
        "gics_sector": "Information Technology",
        "gics_industry": "Communications Equipment",
        "gics_sub_industry_code": "45201020",
        "cyber_sector": "network_security",
        "cyber_focus": ["NGFW", "SD-WAN", "SASE", "OT Security"],
        "description": "Broad cybersecurity platform with network security focus",
    },
    "S": {
        "name": "SentinelOne",
        "ticker": "S",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "endpoint_security",
        "cyber_focus": ["EDR", "XDR", "AI-Powered Security"],
        "description": "AI-powered autonomous endpoint security platform",
    },
    "NET": {
        "name": "Cloudflare",
        "ticker": "NET",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "cloud_security",
        "cyber_focus": ["CDN", "DDoS Protection", "Zero Trust", "Edge Security"],
        "description": "Global cloud platform for security, performance, and reliability",
    },
    "OKTA": {
        "name": "Okta",
        "ticker": "OKTA",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "identity_access",
        "cyber_focus": ["IAM", "SSO", "MFA", "Workforce Identity"],
        "description": "Cloud-based identity and access management platform",
    },
    "CYBR": {
        "name": "CyberArk Software",
        "ticker": "CYBR",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "identity_access",
        "cyber_focus": ["PAM", "Secrets Management", "Identity Security"],
        "description": "Identity security platform focused on privileged access",
    },
    "TENB": {
        "name": "Tenable Holdings",
        "ticker": "TENB",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "vulnerability_management",
        "cyber_focus": [
            "Vulnerability Management",
            "Exposure Management",
            "OT Security",
        ],
        "description": "Exposure management platform for cyber risk visibility",
    },
    "QLYS": {
        "name": "Qualys",
        "ticker": "QLYS",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "vulnerability_management",
        "cyber_focus": ["Vulnerability Management", "Compliance", "Cloud Security"],
        "description": "Cloud-based security and compliance solutions",
    },
    "RPD": {
        "name": "Rapid7",
        "ticker": "RPD",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "security_operations",
        "cyber_focus": ["SIEM", "Vulnerability Management", "Detection & Response"],
        "description": "Security analytics and automation platform",
    },
    "VRNS": {
        "name": "Varonis Systems",
        "ticker": "VRNS",
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "cyber_sector": "data_security",
        "cyber_focus": ["Data Security", "DSPM", "Insider Threat"],
        "description": "Data security platform for visibility and protection",
    },
}


def get_company_taxonomy(ticker: str) -> dict:
    """Get taxonomy information for a tracked company."""
    return TRACKED_COMPANIES.get(ticker.upper(), None)


def get_cyber_sector_info(sector_key: str) -> dict:
    """Get information about a cybersecurity sector."""
    return CYBER_SECTORS.get(sector_key, None)


def get_all_cyber_sectors() -> dict:
    """Get all cybersecurity sector definitions."""
    return CYBER_SECTORS


def get_tracked_tickers() -> list:
    """Get list of all tracked company tickers."""
    return list(TRACKED_COMPANIES.keys())


# -----------------------------------------------------------------------------
# Company Name Aliases for Entity Resolution
# -----------------------------------------------------------------------------
# Maps various ways a company might be mentioned to their canonical ticker.
# This ensures extracted entities are properly linked to tracked companies.

COMPANY_ALIASES = {
    # CrowdStrike variations
    "crowdstrike": "CRWD",
    "crowdstrike holdings": "CRWD",
    "crowd strike": "CRWD",
    "crwd": "CRWD",

    # Palo Alto Networks variations
    "palo alto networks": "PANW",
    "palo alto": "PANW",
    "paloalto": "PANW",
    "pan": "PANW",
    "panw": "PANW",

    # Zscaler variations
    "zscaler": "ZS",
    "z scaler": "ZS",
    "zs": "ZS",

    # Fortinet variations
    "fortinet": "FTNT",
    "forti": "FTNT",
    "ftnt": "FTNT",

    # SentinelOne variations
    "sentinelone": "S",
    "sentinel one": "S",
    "sentinel": "S",
    "s1": "S",

    # Cloudflare variations
    "cloudflare": "NET",
    "cloud flare": "NET",
    "net": "NET",

    # Okta variations
    "okta": "OKTA",

    # CyberArk variations
    "cyberark": "CYBR",
    "cyber ark": "CYBR",
    "cyberark software": "CYBR",
    "cybr": "CYBR",

    # Tenable variations
    "tenable": "TENB",
    "tenable holdings": "TENB",
    "tenb": "TENB",

    # Qualys variations
    "qualys": "QLYS",
    "qlys": "QLYS",

    # Rapid7 variations
    "rapid7": "RPD",
    "rapid 7": "RPD",
    "rpd": "RPD",

    # Varonis variations
    "varonis": "VRNS",
    "varonis systems": "VRNS",
    "vrns": "VRNS",

    # Additional common cybersecurity companies (not tracked but often mentioned)
    # These map to None to indicate "known but not tracked"
    "microsoft": None,
    "google": None,
    "amazon": None,
    "aws": None,
    "cisco": None,
    "ibm": None,
    "check point": None,
    "checkpoint": None,
    "symantec": None,
    "mcafee": None,
    "trend micro": None,
    "sophos": None,
    "kaspersky": None,
    "bitdefender": None,
    "carbon black": None,
    "vmware": None,
    "broadcom": None,
    "netskope": None,
    "proofpoint": None,
    "mimecast": None,
    "sailpoint": None,
    "ping identity": None,
    "beyondtrust": None,
    "thycotic": None,
    "snyk": None,
    "veracode": None,
    "checkmarx": None,
    "synopsys": None,
    "wiz": None,
    "lacework": None,
    "orca security": None,
    "arctic wolf": None,
    "secureworks": None,
    "mandiant": None,
    "fireeye": None,
    "splunk": None,
    "elastic": None,
    "sumo logic": None,
    "datadog": None,
    "dynatrace": None,
}


def resolve_company_name(name: str) -> dict:
    """
    Resolve a company name/alias to its canonical information.

    Args:
        name: Company name as extracted from text

    Returns:
        dict with:
            - ticker: Canonical ticker (or None if not tracked)
            - name: Canonical company name
            - is_tracked: Whether this is a tracked company
            - taxonomy: Full taxonomy info if tracked
    """
    if not name:
        return None

    # Normalize the name for lookup
    normalized = name.lower().strip()

    # Remove common suffixes for matching
    for suffix in [", inc.", ", inc", " inc.", " inc", ", llc", " llc",
                   ", corp.", " corp.", ", ltd.", " ltd."]:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)].strip()

    # Check alias lookup
    if normalized in COMPANY_ALIASES:
        ticker = COMPANY_ALIASES[normalized]
        if ticker:
            taxonomy = TRACKED_COMPANIES.get(ticker)
            return {
                "ticker": ticker,
                "name": taxonomy.get("name") if taxonomy else name,
                "is_tracked": True,
                "taxonomy": taxonomy,
            }
        else:
            # Known company but not tracked
            return {
                "ticker": None,
                "name": name,
                "is_tracked": False,
                "taxonomy": None,
            }

    # Check if it directly matches a tracked company name
    for ticker, info in TRACKED_COMPANIES.items():
        if normalized == info.get("name", "").lower():
            return {
                "ticker": ticker,
                "name": info.get("name"),
                "is_tracked": True,
                "taxonomy": info,
            }

    # Not found in our database
    return None


def get_all_tracked_company_names() -> set:
    """
    Get all known names/aliases for tracked companies.

    Returns:
        Set of normalized company names that are tracked
    """
    names = set()

    # Add all aliases that map to a ticker
    for alias, ticker in COMPANY_ALIASES.items():
        if ticker is not None:
            names.add(alias)

    # Add canonical names
    for ticker, info in TRACKED_COMPANIES.items():
        names.add(info.get("name", "").lower())
        names.add(ticker.lower())

    return names
