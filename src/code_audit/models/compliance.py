"""CWE/OWASP compliance mapping for code audit findings.

Maps the ~30 most common CWE identifiers to OWASP 2021 Top 10 categories.
Used by the Finding model to derive compliance metadata from existing tags.
"""

from __future__ import annotations

# CWE → OWASP 2021 mapping (top ~30 CWEs relevant to code review)
CWE_OWASP_MAP: dict[str, dict[str, str]] = {
    # A01:2021 — Broken Access Control
    "CWE-22": {"owasp": "A01:2021", "name": "Path Traversal", "owasp_name": "Broken Access Control"},
    "CWE-284": {"owasp": "A01:2021", "name": "Improper Access Control", "owasp_name": "Broken Access Control"},
    "CWE-285": {"owasp": "A01:2021", "name": "Improper Authorization", "owasp_name": "Broken Access Control"},
    "CWE-352": {"owasp": "A01:2021", "name": "Cross-Site Request Forgery (CSRF)", "owasp_name": "Broken Access Control"},
    "CWE-639": {"owasp": "A01:2021", "name": "Insecure Direct Object Reference (IDOR)", "owasp_name": "Broken Access Control"},
    # A02:2021 — Cryptographic Failures
    "CWE-259": {"owasp": "A02:2021", "name": "Hard-coded Password", "owasp_name": "Cryptographic Failures"},
    "CWE-327": {"owasp": "A02:2021", "name": "Broken Crypto Algorithm", "owasp_name": "Cryptographic Failures"},
    "CWE-328": {"owasp": "A02:2021", "name": "Weak Hash", "owasp_name": "Cryptographic Failures"},
    "CWE-330": {"owasp": "A02:2021", "name": "Insufficient Randomness", "owasp_name": "Cryptographic Failures"},
    "CWE-611": {"owasp": "A02:2021", "name": "XXE Processing", "owasp_name": "Cryptographic Failures"},
    # A03:2021 — Injection
    "CWE-77": {"owasp": "A03:2021", "name": "Command Injection", "owasp_name": "Injection"},
    "CWE-78": {"owasp": "A03:2021", "name": "OS Command Injection", "owasp_name": "Injection"},
    "CWE-79": {"owasp": "A03:2021", "name": "Cross-Site Scripting (XSS)", "owasp_name": "Injection"},
    "CWE-89": {"owasp": "A03:2021", "name": "SQL Injection", "owasp_name": "Injection"},
    "CWE-90": {"owasp": "A03:2021", "name": "LDAP Injection", "owasp_name": "Injection"},
    "CWE-94": {"owasp": "A03:2021", "name": "Code Injection", "owasp_name": "Injection"},
    "CWE-917": {"owasp": "A03:2021", "name": "Expression Language Injection", "owasp_name": "Injection"},
    # A04:2021 — Insecure Design
    "CWE-209": {"owasp": "A04:2021", "name": "Error Message Information Leak", "owasp_name": "Insecure Design"},
    "CWE-502": {"owasp": "A04:2021", "name": "Deserialization of Untrusted Data", "owasp_name": "Insecure Design"},
    # A05:2021 — Security Misconfiguration
    "CWE-16": {"owasp": "A05:2021", "name": "Configuration", "owasp_name": "Security Misconfiguration"},
    "CWE-614": {"owasp": "A05:2021", "name": "Sensitive Cookie Without Secure Flag", "owasp_name": "Security Misconfiguration"},
    "CWE-942": {"owasp": "A05:2021", "name": "Overly Permissive CORS", "owasp_name": "Security Misconfiguration"},
    # A06:2021 — Vulnerable and Outdated Components
    "CWE-1104": {"owasp": "A06:2021", "name": "Unmaintained Third-Party Components", "owasp_name": "Vulnerable and Outdated Components"},
    # A07:2021 — Identification and Authentication Failures
    "CWE-287": {"owasp": "A07:2021", "name": "Improper Authentication", "owasp_name": "Identification and Authentication Failures"},
    "CWE-798": {"owasp": "A07:2021", "name": "Hard-coded Credentials", "owasp_name": "Identification and Authentication Failures"},
    "CWE-306": {"owasp": "A07:2021", "name": "Missing Authentication", "owasp_name": "Identification and Authentication Failures"},
    # A08:2021 — Software and Data Integrity Failures
    "CWE-345": {"owasp": "A08:2021", "name": "Insufficient Verification of Data Authenticity", "owasp_name": "Software and Data Integrity Failures"},
    # A09:2021 — Security Logging and Monitoring Failures
    "CWE-778": {"owasp": "A09:2021", "name": "Insufficient Logging", "owasp_name": "Security Logging and Monitoring Failures"},
    # A10:2021 — Server-Side Request Forgery (SSRF)
    "CWE-918": {"owasp": "A10:2021", "name": "Server-Side Request Forgery (SSRF)", "owasp_name": "Server-Side Request Forgery"},
}


def extract_cwe_ids(tags: list[str]) -> list[str]:
    """Extract CWE identifiers from a finding's tags list.

    Tags should use the format 'cwe-NNN' (case-insensitive).
    Returns normalized uppercase IDs like ['CWE-79', 'CWE-89'].
    """
    cwe_ids: list[str] = []
    for tag in tags:
        lower = tag.lower().strip()
        if lower.startswith("cwe-"):
            # Normalize: 'cwe-79' → 'CWE-79'
            cwe_id = "CWE-" + lower[4:]
            cwe_ids.append(cwe_id)
    return cwe_ids


def map_cwes_to_owasp(cwe_ids: list[str]) -> list[str]:
    """Map a list of CWE IDs to their OWASP 2021 Top 10 categories.

    Returns deduplicated list like ['A03:2021 Injection', 'A07:2021 Identification and Authentication Failures'].
    """
    seen: set[str] = set()
    result: list[str] = []
    for cwe_id in cwe_ids:
        entry = CWE_OWASP_MAP.get(cwe_id)
        if entry and entry["owasp"] not in seen:
            seen.add(entry["owasp"])
            result.append(f"{entry['owasp']} {entry['owasp_name']}")
    return result
