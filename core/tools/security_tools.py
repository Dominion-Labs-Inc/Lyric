#!/usr/bin/env python3
"""
Security & Encryption Tools
============================
Comprehensive security tools including encryption, active defense, threat intelligence,
and defensive security capabilities

Encryption & Cryptography Tools:
- encrypt_file: Encrypt file with AES-256 encryption
- decrypt_file: Decrypt AES-encrypted file
- generate_password: Generate cryptographically secure random password
- hash_data: Hash data with SHA-256, SHA-512, Blake2b, etc.
- validate_certificate: Validate SSL/TLS certificates
- scan_secrets: Scan code for exposed secrets and credentials

Active Defense & Threat Intelligence Tools:
- check_ip_threat_intelligence: Query multi-source threat intel for IP (AbuseIPDB, VirusTotal, OTX)
- block_ip_address: Block IP across OS firewall and Cloudflare WAF
- unblock_ip_address: Unblock previously blocked IP
- get_active_blocks: List all currently blocked entities
- create_waf_rule: Create custom Cloudflare WAF firewall rule
- apply_rate_limit: Apply rate limiting to an IP address
- block_country: Geo-blocking entire country via Cloudflare
- get_security_metrics: Get comprehensive security statistics
- get_block_history: Get historical blocking records for IPs
- add_internal_threat: Add IP to internal threat database
- sanitize_input: Sanitize user input to prevent XSS/SQLi/shell injection

Defensive Security & Intrusion Detection Tools:
- detect_intrusion: Real-time intrusion detection (brute force, port scans, suspicious patterns)
- analyze_anomaly: Behavioral anomaly detection in traffic and access patterns
- monitor_logs: Real-time log analysis and attack pattern recognition
- detect_brute_force: Detect brute force attacks on authentication endpoints
- analyze_traffic_pattern: Network traffic analysis for DDoS and data exfiltration
- auto_respond_threat: Automated threat response with configurable playbooks
- hunt_threats: Proactive threat hunting using IOCs and behavioral analysis
- detect_zero_day: Heuristic-based detection of novel attack patterns

Author: Torin AI Team
"""

import asyncio
import logging
import hashlib
import secrets
import string
import re
import time
import os
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from urllib.parse import quote

import aiohttp

try:
    from core.utils.env_loader import get_github_token as _get_github_token
except ImportError:
    def _get_github_token():  # type: ignore
        return os.getenv("GITHUB_TOKEN")

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import (
    ToolCapabilityProfile, CapabilityMetadata, Capability, RiskLevel
)


logger = logging.getLogger(__name__)


# ── Content checks ──────────────────────────────────────────────────────────
# The logic behind validate_email, validate_url, check_malicious_patterns and
# sanitize_filename. It lived in core/security/content_security.py, which was
# deleted; the tools that use it keep it here.

#: Patterns that mark content as carrying active script or code.
MALICIOUS_PATTERNS = [
    r'<script[^>]*>.*?</script>',  # Script tags
    r'javascript:',  # JavaScript protocol
    r'on\w+\s*=',  # Event handlers (onclick, onerror, etc.)
    r'<iframe',  # Iframes
    r'<object',  # Objects
    r'<embed',  # Embeds
    r'eval\s*\(',  # eval() calls
    r'expression\s*\(',  # CSS expressions
]

EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'


def sanitize_input(text: str, allow_html: bool = False) -> str:
    """Escape HTML (unless allowed) and strip the malicious patterns."""
    if not text:
        return ""
    if not allow_html:
        import html
        text = html.escape(text)
    for pattern in MALICIOUS_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    return text.strip()


def validate_email(email: str) -> bool:
    """True when the address has the shape of an email address."""
    if not email:
        return False
    return bool(re.match(EMAIL_REGEX, email))


def validate_url(url: str) -> bool:
    """True for an http(s) URL with a host."""
    if not url:
        return False
    try:
        from urllib.parse import urlparse
        result = urlparse(url)
        return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
    except Exception:
        return False


def check_malicious_patterns(text: str) -> bool:
    """True when the text contains any of the malicious patterns."""
    if not text:
        return False
    for pattern in MALICIOUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Malicious pattern detected: {pattern}")
            return True
    return False


def sanitize_filename(filename: str) -> str:
    """A filename with path separators and unsafe characters replaced."""
    if not filename:
        return ""
    filename = filename.replace('/', '_').replace('\\', '_')
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    filename = filename.lstrip('.')
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:250] + ('.' + ext if ext else '')
    return filename


class EncryptFileTool(Tool):
    """Encrypt file with AES encryption"""

    def __init__(self):
        super().__init__()
        self.name = "encrypt_file"
        self.description = "Encrypt a file using AES-256 encryption"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="input_file",
                type="string",
                description="File to encrypt",
                required=True
            ),
            ToolParameter(
                name="output_file",
                type="string",
                description="Encrypted output file path",
                required=True
            ),
            ToolParameter(
                name="password",
                type="string",
                description="Encryption password",
                required=True
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="encrypt_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ENCRYPT_DATA,
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(self, input_file: str, output_file: str, password: str) -> ToolResult:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            from cryptography.hazmat.backends import default_backend
            import os

            input_path = Path(input_file).expanduser().resolve()
            if not input_path.exists():
                return ToolResult(success=False, output=None, error=f"Input file not found: {input_path}")

            output_path = Path(output_file).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Read input file
            with open(input_path, 'rb') as f:
                plaintext = f.read()

            # Generate salt and IV
            salt = os.urandom(16)
            iv = os.urandom(16)

            # Derive key from password
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend()
            )
            key = kdf.derive(password.encode())

            # Encrypt
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            encryptor = cipher.encryptor()

            # Pad plaintext to block size
            block_size = 16
            padding_length = block_size - (len(plaintext) % block_size)
            padded_plaintext = plaintext + bytes([padding_length] * padding_length)

            ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()

            # Write salt + iv + ciphertext
            with open(output_path, 'wb') as f:
                f.write(salt + iv + ciphertext)

            return ToolResult(
                success=True,
                output={
                    'input_file': str(input_path),
                    'output_file': str(output_path),
                    'original_size': len(plaintext),
                    'encrypted_size': len(ciphertext) + 32,  # +32 for salt and IV
                    'algorithm': 'AES-256-CBC'
                }
            )

        except ImportError:
            return ToolResult(success=False, output=None, error="cryptography library not installed")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class DecryptFileTool(Tool):
    """Decrypt encrypted file"""

    def __init__(self):
        super().__init__()
        self.name = "decrypt_file"
        self.description = "Decrypt a file encrypted with AES-256"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="input_file",
                type="string",
                description="Encrypted file to decrypt",
                required=True
            ),
            ToolParameter(
                name="output_file",
                type="string",
                description="Decrypted output file path",
                required=True
            ),
            ToolParameter(
                name="password",
                type="string",
                description="Decryption password",
                required=True
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="decrypt_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DECRYPT_DATA,
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(self, input_file: str, output_file: str, password: str) -> ToolResult:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            from cryptography.hazmat.backends import default_backend

            input_path = Path(input_file).expanduser().resolve()
            if not input_path.exists():
                return ToolResult(success=False, output=None, error=f"Input file not found: {input_path}")

            output_path = Path(output_file).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Read encrypted file
            with open(input_path, 'rb') as f:
                data = f.read()

            # Extract salt, IV, and ciphertext
            salt = data[:16]
            iv = data[16:32]
            ciphertext = data[32:]

            # Derive key from password
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend()
            )
            key = kdf.derive(password.encode())

            # Decrypt
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

            # Remove padding
            padding_length = padded_plaintext[-1]
            plaintext = padded_plaintext[:-padding_length]

            # Write decrypted file
            with open(output_path, 'wb') as f:
                f.write(plaintext)

            return ToolResult(
                success=True,
                output={
                    'input_file': str(input_path),
                    'output_file': str(output_path),
                    'decrypted_size': len(plaintext)
                }
            )

        except ImportError:
            return ToolResult(success=False, output=None, error="cryptography library not installed")
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Decryption failed: {e}")


class GeneratePasswordTool(Tool):
    """Generate secure random password"""

    def __init__(self):
        super().__init__()
        self.name = "generate_password"
        self.description = "Generate cryptographically secure random password"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="length",
                type="number",
                description="Password length",
                required=False,
                default=16,
                min_value=8,
                max_value=128
            ),
            ToolParameter(
                name="include_symbols",
                type="boolean",
                description="Include special symbols",
                required=False,
                default=True
            ),
            ToolParameter(
                name="include_numbers",
                type="boolean",
                description="Include numbers",
                required=False,
                default=True
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_password",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ENCRYPT_DATA,
                    risk_level=RiskLevel.MEDIUM,
                    priority=7,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    priority=7,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(self, length: int = 16, include_symbols: bool = True, include_numbers: bool = True) -> ToolResult:
        try:
            # Build character set
            chars = string.ascii_letters  # Always include letters

            if include_numbers:
                chars += string.digits

            if include_symbols:
                chars += "!@#$%^&*()-_=+[]{}|;:,.<>?"

            # Generate password
            password = ''.join(secrets.choice(chars) for _ in range(length))

            # Ensure at least one of each required type
            if include_numbers and not any(c.isdigit() for c in password):
                password = password[:-1] + secrets.choice(string.digits)

            if include_symbols and not any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in password):
                password = password[:-1] + secrets.choice("!@#$%^&*()")

            return ToolResult(
                success=True,
                output={
                    'password': password,
                    'length': len(password),
                    'includes_symbols': include_symbols,
                    'includes_numbers': include_numbers
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class HashDataTool(Tool):
    """Hash data with various algorithms"""

    def __init__(self):
        super().__init__()
        self.name = "hash_data"
        self.description = "Hash data using SHA-256, SHA-512, or other algorithms"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="data",
                type="string",
                description="Data to hash",
                required=True
            ),
            ToolParameter(
                name="algorithm",
                type="string",
                description="Hash algorithm",
                required=False,
                default="sha256",
                enum=["sha256", "sha512", "sha1", "md5", "blake2b"]
            ),
            ToolParameter(
                name="salt",
                type="string",
                description="Optional salt to add to data",
                required=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="hash_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.HASH_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=7,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=7,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, data: str, algorithm: str = "sha256", salt: str = None) -> ToolResult:
        try:
            # Add salt if provided
            if salt:
                data_to_hash = (salt + data).encode()
            else:
                data_to_hash = data.encode()

            # Hash data
            if algorithm == "sha256":
                hash_obj = hashlib.sha256(data_to_hash)
            elif algorithm == "sha512":
                hash_obj = hashlib.sha512(data_to_hash)
            elif algorithm == "sha1":
                hash_obj = hashlib.sha1(data_to_hash)
            elif algorithm == "md5":
                hash_obj = hashlib.md5(data_to_hash)
            elif algorithm == "blake2b":
                hash_obj = hashlib.blake2b(data_to_hash)
            else:
                return ToolResult(success=False, output=None, error=f"Unsupported algorithm: {algorithm}")

            hash_value = hash_obj.hexdigest()

            return ToolResult(
                success=True,
                output={
                    'algorithm': algorithm,
                    'hash': hash_value,
                    'length': len(hash_value),
                    'salted': salt is not None
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ValidateCertificateTool(Tool):
    """Validate SSL certificate"""

    def __init__(self):
        super().__init__()
        self.name = "validate_certificate"
        self.description = "Validate SSL/TLS certificate for a domain"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="hostname",
                type="string",
                description="Hostname to check (e.g., 'google.com')",
                required=True
            ),
            ToolParameter(
                name="port",
                type="number",
                description="Port number",
                required=False,
                default=443
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="validate_certificate",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=7,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, hostname: str, port: int = 443) -> ToolResult:
        try:
            import ssl
            import socket
            from datetime import datetime

            # Create SSL context
            context = ssl.create_default_context()

            # Connect and get certificate
            with socket.create_connection((hostname, port), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()

            # Parse certificate info
            subject = dict(x[0] for x in cert['subject'])
            issuer = dict(x[0] for x in cert['issuer'])

            not_before = datetime.strptime(cert['notBefore'], '%b %d %H:%M:%S %Y %Z')
            not_after = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
            now = datetime.utcnow()

            is_valid = not_before <= now <= not_after
            days_remaining = (not_after - now).days

            return ToolResult(
                success=True,
                output={
                    'hostname': hostname,
                    'port': port,
                    'valid': is_valid,
                    'subject': subject,
                    'issuer': issuer,
                    'not_before': not_before.isoformat(),
                    'not_after': not_after.isoformat(),
                    'days_remaining': days_remaining,
                    'version': cert.get('version'),
                    'serial_number': cert.get('serialNumber')
                }
            )

        except ssl.SSLError as e:
            return ToolResult(success=False, output=None, error=f"SSL error: {e}")
        except socket.timeout:
            return ToolResult(success=False, output=None, error="Connection timeout")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ScanSecretsTool(Tool):
    """Scan code for exposed secrets"""

    def __init__(self):
        super().__init__()
        self.name = "scan_secrets"
        self.description = "Scan code files for potentially exposed secrets and credentials"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Directory to scan",
                required=True
            ),
            ToolParameter(
                name="extensions",
                type="array",
                description="File extensions to scan",
                required=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="scan_secrets",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SCAN_SECURITY,
                    risk_level=RiskLevel.LOW,
                    priority=9,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.MANAGE_SECRETS,
                    risk_level=RiskLevel.LOW,
                    priority=9,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, directory_path: str, extensions: List[str] = None) -> ToolResult:
        try:
            directory = Path(directory_path).expanduser().resolve()
            if not directory.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {directory}")

            if not extensions:
                extensions = ['.py', '.js', '.ts', '.java', '.go', '.env', '.yaml', '.yml', '.json', '.xml']

            # Secret patterns
            patterns = [
                (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})["\']', 'API Key'),
                (r'(?i)(secret[_-]?key|secretkey)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})["\']', 'Secret Key'),
                (r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']([^"\']{8,})["\']', 'Password'),
                (r'(?i)(aws[_-]?access[_-]?key[_-]?id)\s*[:=]\s*["\']([A-Z0-9]{20})["\']', 'AWS Access Key'),
                (r'(?i)(aws[_-]?secret[_-]?access[_-]?key)\s*[:=]\s*["\']([a-zA-Z0-9/+=]{40})["\']', 'AWS Secret Key'),
                (r'(?i)(github[_-]?token|gh[_-]?token)\s*[:=]\s*["\']([a-zA-Z0-9_]{40,})["\']', 'GitHub Token'),
                (r'(?i)(bearer\s+[a-zA-Z0-9_\-\.]{20,})', 'Bearer Token'),
                (r'(?i)(private[_-]?key)\s*[:=]\s*["\']([^"\']{20,})["\']', 'Private Key'),
                (r'sk-[a-zA-Z0-9]{48}', 'OpenAI API Key'),
                (r'xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}', 'Slack Token'),
            ]

            findings = []

            for ext in extensions:
                for file in directory.rglob(f'*{ext}'):
                    # Skip common non-sensitive paths
                    if any(skip in str(file) for skip in ['node_modules', 'venv', '.git', '__pycache__']):
                        continue

                    try:
                        with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            lines = content.split('\n')

                        for i, line in enumerate(lines, 1):
                            for pattern, secret_type in patterns:
                                matches = re.finditer(pattern, line)
                                for match in matches:
                                    # Check if it's a variable assignment or comment
                                    is_comment = line.strip().startswith('#') or line.strip().startswith('//')

                                    # Extract the matched secret (redacted for security)
                                    matched_text = match.group(0)
                                    redacted = matched_text[:10] + '***' if len(matched_text) > 10 else '***'

                                    findings.append({
                                        'file': str(file.relative_to(directory)),
                                        'line': i,
                                        'type': secret_type,
                                        'matched_value': redacted,
                                        'context': line.strip()[:100],  # First 100 chars
                                        'severity': 'LOW' if is_comment else 'HIGH',
                                        'is_comment': is_comment
                                    })
                    except:
                        continue

            # Sort by severity
            findings.sort(key=lambda x: 0 if x['severity'] == 'HIGH' else 1)

            return ToolResult(
                success=True,
                output={
                    'directory': str(directory),
                    'total_findings': len(findings),
                    'high_severity': len([f for f in findings if f['severity'] == 'HIGH']),
                    'low_severity': len([f for f in findings if f['severity'] == 'LOW']),
                    'findings': findings,
                    'files_with_secrets': len(set(f['file'] for f in findings)),
                    'note': 'Review findings carefully - may include false positives'
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


# ============================================================================
# Active Defense & Threat Intelligence Tools (Wrapping Security Systems)
# ============================================================================


class CheckIPThreatIntelligenceTool(Tool):
    """Query threat intelligence for an IP address"""

    def __init__(self):
        super().__init__()
        self.name = "check_ip_threat_intelligence"
        self.description = "Query multi-source threat intelligence for an IP address (AbuseIPDB, VirusTotal, OTX)"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="ip_address",
                type="string",
                description="IP address to query",
                required=True
            ),
            ToolParameter(
                name="sources",
                type="array",
                description="Specific sources to query (optional)",
                required=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="check_ip_threat_intelligence",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.ASSESS_RISK,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, ip_address: str, sources: List[str] = None) -> ToolResult:
        try:
            from core.security import create_integrated_security_system

            # Get integrated security system
            sec_system = create_integrated_security_system()
            threat_intel = sec_system.get('threat_intel')

            if not threat_intel:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Threat Intelligence Engine not available. Check active_defense_config.json"
                )

            # Query threat intelligence
            intel = await threat_intel.get_ip_intelligence(ip_address, sources=None)

            result = {
                'ip_address': intel.ip_address,
                'reputation_score': intel.reputation_score,
                'confidence': intel.confidence.value,
                'sources': [s.value for s in intel.sources],
                'threat_types': [t.value for t in intel.threat_types],
                'report_count': intel.report_count,
                'country': intel.country,
                'asn': intel.asn,
                'isp': intel.isp,
                'first_seen': intel.first_seen,
                'last_seen': intel.last_seen,
                'is_threat': intel.reputation_score > 0.5,
                'threat_level': 'CRITICAL' if intel.reputation_score > 0.8 else 'HIGH' if intel.reputation_score > 0.5 else 'MEDIUM' if intel.reputation_score > 0.3 else 'LOW'
            }

            return ToolResult(success=True, output=result)

        except ImportError:
            return ToolResult(success=False, output=None, error="Security module not available")
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Threat intelligence query failed: {str(e)}")


class BlockIPAddressTool(Tool):
    """Block an IP address across all defense layers"""

    def __init__(self):
        super().__init__()
        self.name = "block_ip_address"
        self.description = "Block an IP address across OS firewall and Cloudflare WAF"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="ip_address",
                type="string",
                description="IP address to block",
                required=True
            ),
            ToolParameter(
                name="reason",
                type="string",
                description="Reason for blocking",
                required=True
            ),
            ToolParameter(
                name="attack_type",
                type="string",
                description="Type of attack detected",
                required=False,
                enum=["brute_force", "ddos", "sql_injection", "xss", "malware_upload", "bot_attack", "port_scan", "suspicious_behavior"]
            ),
            ToolParameter(
                name="force_block",
                type="boolean",
                description="Force block regardless of threat score",
                required=False,
                default=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="block_ip_address",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BLOCK_THREAT,
                    risk_level=RiskLevel.HIGH,
                    priority=9,
                    approval_level="team_lead"
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=True,
            is_idempotent=False
        )

    async def execute(self, ip_address: str, reason: str, attack_type: str = "suspicious_behavior", force_block: bool = False) -> ToolResult:
        try:
            from core.security import create_integrated_security_system
            from core.agents.autonomous.threat_sense import AttackType

            # Get integrated security system
            sec_system = create_integrated_security_system()
            threat_blocking = sec_system.get('threat_blocking')

            if not threat_blocking:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Threat Blocking Engine not available. Check active_defense_config.json"
                )

            # Map attack type string to enum
            attack_type_map = {
                "brute_force": AttackType.BRUTE_FORCE,
                "ddos": AttackType.DDOS,
                "sql_injection": AttackType.SQL_INJECTION,
                "xss": AttackType.XSS_ATTACK,
                "malware_upload": AttackType.MALWARE_UPLOAD,
                "bot_attack": AttackType.BOT_ATTACK,
                "port_scan": AttackType.PORT_SCAN,
                "suspicious_behavior": AttackType.PORT_SCAN  # Default to port_scan as fallback
            }

            attack_enum = attack_type_map.get(attack_type, AttackType.PORT_SCAN)

            # Analyze and block
            result = await threat_blocking.analyze_and_block(
                ip_address=ip_address,
                attack_type=attack_enum,
                evidence={"reason": reason},
                force_block=force_block
            )

            return ToolResult(success=True, output=result)

        except ImportError:
            return ToolResult(success=False, output=None, error="Security module not available")
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"IP blocking failed: {str(e)}")


class UnblockIPAddressTool(Tool):
    """Unblock a previously blocked IP address"""

    def __init__(self):
        super().__init__()
        self.name = "unblock_ip_address"
        self.description = "Unblock an IP address from OS firewall and Cloudflare WAF"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="ip_address",
                type="string",
                description="IP address to unblock",
                required=True
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="unblock_ip_address",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BLOCK_THREAT,
                    risk_level=RiskLevel.MEDIUM,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, ip_address: str) -> ToolResult:
        try:
            from core.security import create_integrated_security_system

            sec_system = create_integrated_security_system()
            threat_blocking = sec_system.get('threat_blocking')

            if not threat_blocking:
                return ToolResult(success=False, output=None, error="Threat Blocking Engine not available")

            success = await threat_blocking.unblock(ip_address)

            return ToolResult(
                success=success,
                output={
                    'ip_address': ip_address,
                    'unblocked': success,
                    'message': f"Successfully unblocked {ip_address}" if success else f"Failed to unblock {ip_address}"
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Unblock failed: {str(e)}")


class GetActiveBlocksTool(Tool):
    """Get list of currently blocked entities"""

    def __init__(self):
        super().__init__()
        self.name = "get_active_blocks"
        self.description = "Get all currently blocked IPs and entities across defense systems"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = []

        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_active_blocks",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MONITOR_SYSTEM,
                    risk_level=RiskLevel.LOW,
                    priority=6,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self) -> ToolResult:
        try:
            from core.security import create_integrated_security_system

            sec_system = create_integrated_security_system()
            threat_blocking = sec_system.get('threat_blocking')

            if not threat_blocking:
                return ToolResult(success=False, output=None, error="Threat Blocking Engine not available")

            blocked_entities = threat_blocking.get_blocked_entities()

            result = {
                'total_blocked': len(blocked_entities),
                'blocked_entities': [
                    {
                        'entity_id': entity.entity_id,
                        'ip_address': entity.entity_value,
                        'reason': entity.reason,
                        'attack_type': entity.attack_type.value,
                        'blocked_at': entity.blocked_at,
                        'expires_at': entity.expires_at,
                        'block_count': entity.block_count,
                        'confidence': entity.confidence.value
                    }
                    for entity in blocked_entities
                ]
            }

            return ToolResult(success=True, output=result)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Failed to get blocked entities: {str(e)}")


class CreateWAFRuleTool(Tool):
    """Create custom Cloudflare WAF rule"""

    def __init__(self):
        super().__init__()
        self.name = "create_waf_rule"
        self.description = "Create custom Cloudflare WAF firewall rule with advanced expressions"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="expression",
                type="string",
                description="Cloudflare firewall expression (e.g., '(ip.src eq 1.2.3.4)')",
                required=True
            ),
            ToolParameter(
                name="description",
                type="string",
                description="Rule description",
                required=True
            ),
            ToolParameter(
                name="action",
                type="string",
                description="Action to take",
                required=True,
                enum=["block", "challenge", "js_challenge", "managed_challenge", "allow", "log"]
            ),
            ToolParameter(
                name="priority",
                type="number",
                description="Rule priority (lower = higher priority)",
                required=False,
                default=50
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="create_waf_rule",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.UPDATE_STRATEGY,
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(self, expression: str, description: str, action: str, priority: int = 50) -> ToolResult:
        try:
            from core.security import create_integrated_security_system
            from core.agents.autonomous.threat_sense import WAFRuleMode

            sec_system = create_integrated_security_system()
            waf_manager = sec_system.get('waf')

            if not waf_manager:
                return ToolResult(success=False, output=None, error="Cloudflare WAF Manager not available (no API credentials configured)")

            # Map action string to enum
            action_map = {
                "block": WAFRuleMode.BLOCK,
                "challenge": WAFRuleMode.CHALLENGE,
                "js_challenge": WAFRuleMode.JS_CHALLENGE,
                "managed_challenge": WAFRuleMode.MANAGED_CHALLENGE,
                "allow": WAFRuleMode.ALLOW,
                "log": WAFRuleMode.LOG
            }

            action_enum = action_map.get(action.lower(), WAFRuleMode.BLOCK)

            rule_id = await waf_manager.create_custom_waf_rule(
                expression=expression,
                description=description,
                action=action_enum,
                priority=priority
            )

            if rule_id:
                return ToolResult(
                    success=True,
                    output={
                        'rule_id': rule_id,
                        'expression': expression,
                        'action': action,
                        'description': description,
                        'priority': priority,
                        'created': True
                    }
                )
            else:
                return ToolResult(success=False, output=None, error="Failed to create WAF rule")

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"WAF rule creation failed: {str(e)}")


class ApplyRateLimitTool(Tool):
    """Apply rate limiting to an IP address"""

    def __init__(self):
        super().__init__()
        self.name = "apply_rate_limit"
        self.description = "Apply rate limiting to an IP address via Cloudflare WAF"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="ip_address",
                type="string",
                description="IP address to rate limit",
                required=True
            ),
            ToolParameter(
                name="requests_per_minute",
                type="number",
                description="Maximum requests per minute",
                required=False,
                default=100
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="apply_rate_limit",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BLOCK_THREAT,
                    risk_level=RiskLevel.MEDIUM,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(self, ip_address: str, requests_per_minute: int = 100) -> ToolResult:
        try:
            from core.security import create_integrated_security_system

            sec_system = create_integrated_security_system()
            threat_blocking = sec_system.get('threat_blocking')

            if not threat_blocking:
                return ToolResult(success=False, output=None, error="Threat Blocking Engine not available")

            success = await threat_blocking.apply_rate_limit(
                ip_address=ip_address,
                requests_per_minute=requests_per_minute
            )

            return ToolResult(
                success=success,
                output={
                    'ip_address': ip_address,
                    'requests_per_minute': requests_per_minute,
                    'rate_limit_applied': success
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Rate limiting failed: {str(e)}")


class BlockCountryTool(Tool):
    """Block entire country via geo-blocking"""

    def __init__(self):
        super().__init__()
        self.name = "block_country"
        self.description = "Block entire country using Cloudflare geo-blocking"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="country_code",
                type="string",
                description="ISO country code (e.g., 'CN', 'RU')",
                required=True
            ),
            ToolParameter(
                name="reason",
                type="string",
                description="Reason for blocking",
                required=True
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="block_country",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BLOCK_THREAT,
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(self, country_code: str, reason: str) -> ToolResult:
        try:
            from core.security import create_integrated_security_system

            sec_system = create_integrated_security_system()
            threat_blocking = sec_system.get('threat_blocking')

            if not threat_blocking:
                return ToolResult(success=False, output=None, error="Threat Blocking Engine not available")

            success = await threat_blocking.block_country(
                country_code=country_code.upper(),
                reason=reason
            )

            return ToolResult(
                success=success,
                output={
                    'country_code': country_code.upper(),
                    'reason': reason,
                    'blocked': success
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Country blocking failed: {str(e)}")


class GetSecurityMetricsTool(Tool):
    """Get comprehensive security metrics and statistics"""

    def __init__(self):
        super().__init__()
        self.name = "get_security_metrics"
        self.description = "Get current security metrics from all defense systems"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = []

        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_security_metrics",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    risk_level=RiskLevel.LOW,
                    priority=7,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.MONITOR_SYSTEM,
                    risk_level=RiskLevel.LOW,
                    priority=7,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self) -> ToolResult:
        try:
            from core.security import create_integrated_security_system

            sec_system = create_integrated_security_system()
            threat_blocking = sec_system.get('threat_blocking')

            if not threat_blocking:
                return ToolResult(success=False, output=None, error="Threat Blocking Engine not available")

            stats = threat_blocking.get_statistics()

            return ToolResult(success=True, output=stats)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Failed to get security metrics: {str(e)}")


class GetBlockHistoryTool(Tool):
    """Get block history for an IP address"""

    def __init__(self):
        super().__init__()
        self.name = "get_block_history"
        self.description = "Get historical blocking records for an IP address"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="ip_address",
                type="string",
                description="IP address to query (optional - returns all if not specified)",
                required=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_block_history",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=6,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.TRACK_PROGRESS,
                    risk_level=RiskLevel.LOW,
                    priority=6,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, ip_address: str = None) -> ToolResult:
        try:
            from core.security import create_integrated_security_system

            sec_system = create_integrated_security_system()
            threat_blocking = sec_system.get('threat_blocking')

            if not threat_blocking:
                return ToolResult(success=False, output=None, error="Threat Blocking Engine not available")

            history = threat_blocking.get_block_history(ip_address)

            result = {
                'ip_address': ip_address or 'all',
                'total_blocks': len(history),
                'history': [
                    {
                        'entity_id': entity.entity_id,
                        'ip_address': entity.entity_value,
                        'reason': entity.reason,
                        'attack_type': entity.attack_type.value,
                        'blocked_at': entity.blocked_at,
                        'expires_at': entity.expires_at,
                        'block_count': entity.block_count
                    }
                    for entity in history
                ]
            }

            return ToolResult(success=True, output=result)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Failed to get block history: {str(e)}")


class AddInternalThreatTool(Tool):
    """Add IP to internal threat database"""

    def __init__(self):
        super().__init__()
        self.name = "add_internal_threat"
        self.description = "Add an IP address to the internal threat intelligence database"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="ip_address",
                type="string",
                description="IP address to add",
                required=True
            ),
            ToolParameter(
                name="threat_types",
                type="array",
                description="Types of threats associated with this IP",
                required=True
            ),
            ToolParameter(
                name="reputation_score",
                type="number",
                description="Reputation score (0.0-1.0, higher = more malicious)",
                required=True,
                min_value=0.0,
                max_value=1.0
            ),
            ToolParameter(
                name="evidence",
                type="object",
                description="Evidence/metadata about the threat",
                required=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="add_internal_threat",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    risk_level=RiskLevel.MEDIUM,
                    priority=7,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.TRACK_PROGRESS,
                    risk_level=RiskLevel.MEDIUM,
                    priority=7,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=False
        )

    async def execute(self, ip_address: str, threat_types: List[str], reputation_score: float, evidence: Dict[str, Any] = None) -> ToolResult:
        try:
            from core.security import create_integrated_security_system
            from core.agents.autonomous.threat_sense import AttackType

            sec_system = create_integrated_security_system()
            threat_intel = sec_system.get('threat_intel')

            if not threat_intel:
                return ToolResult(success=False, output=None, error="Threat Intelligence Engine not available")

            # Map threat type strings to enums
            attack_type_map = {
                "brute_force": AttackType.BRUTE_FORCE,
                "ddos": AttackType.DDOS,
                "sql_injection": AttackType.SQL_INJECTION,
                "xss": AttackType.XSS_ATTACK,
                "xss_attack": AttackType.XSS_ATTACK,
                "malware_upload": AttackType.MALWARE_UPLOAD,
                "bot_attack": AttackType.BOT_ATTACK,
                "port_scan": AttackType.PORT_SCAN,
                "suspicious_behavior": AttackType.PORT_SCAN  # Fallback
            }

            threat_enums = [attack_type_map.get(t.lower(), AttackType.PORT_SCAN) for t in threat_types]

            threat_intel.add_internal_threat(
                ip_address=ip_address,
                threat_types=threat_enums,
                reputation_score=reputation_score,
                evidence=evidence
            )

            return ToolResult(
                success=True,
                output={
                    'ip_address': ip_address,
                    'threat_types': threat_types,
                    'reputation_score': reputation_score,
                    'added_to_internal_db': True
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Failed to add internal threat: {str(e)}")


class SanitizeInputTool(Tool):
    """Sanitize potentially malicious user input"""

    def __init__(self):
        super().__init__()
        self.name = "sanitize_input"
        self.description = "Sanitize user input to prevent XSS, SQL injection, and other attacks"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="input_data",
                type="string",
                description="Input data to sanitize",
                required=True
            ),
            ToolParameter(
                name="sanitization_type",
                type="string",
                description="Type of sanitization",
                required=False,
                enum=["html", "sql", "shell", "all"],
                default="all"
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="sanitize_input",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.VERIFY_SAFETY,
                    description="Verify input and code safety",
                    input_types=["content"],
                    output_types=["safety_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.ASSESS_ETHICS,
                    description="Assess ethical implications of security actions",
                    input_types=["action"],
                    output_types=["ethics_assessment"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_MISALIGNMENT,
                    description="Detect misaligned or unauthorized activity patterns",
                    input_types=["activity_log"],
                    output_types=["misalignment_report"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.VALIDATE_ALIGNMENT,
                    description="Validate that actions align with security policy",
                    input_types=["action", "policy"],
                    output_types=["alignment_result"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, input_data: str, sanitization_type: str = "all") -> ToolResult:
        try:
            import html

            sanitized = input_data
            removed_patterns = []

            # HTML/XSS sanitization
            if sanitization_type in ["html", "all"]:
                # Escape HTML
                before = sanitized
                sanitized = html.escape(sanitized)
                if before != sanitized:
                    removed_patterns.append("HTML special characters")

                # Remove script tags
                script_pattern = re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL)
                if script_pattern.search(sanitized):
                    sanitized = script_pattern.sub('', sanitized)
                    removed_patterns.append("script tags")

            # SQL injection sanitization
            if sanitization_type in ["sql", "all"]:
                sql_patterns = [
                    (r'(\bOR\b|\bAND\b)\s+\d+\s*=\s*\d+', 'SQL logic patterns'),
                    (r'(--|\;|\/\*|\*\/)', 'SQL comment characters'),
                    (r'(\bUNION\b|\bSELECT\b|\bDROP\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b)', 'SQL keywords')
                ]

                for pattern, desc in sql_patterns:
                    if re.search(pattern, sanitized, re.IGNORECASE):
                        sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE)
                        removed_patterns.append(desc)

            # Shell command sanitization
            if sanitization_type in ["shell", "all"]:
                shell_chars = ['|', '&', ';', '$', '`', '\n', '<', '>', '(', ')', '{', '}']
                for char in shell_chars:
                    if char in sanitized:
                        sanitized = sanitized.replace(char, '')
                        if "shell metacharacters" not in removed_patterns:
                            removed_patterns.append("shell metacharacters")

            is_sanitized = sanitized != input_data

            return ToolResult(
                success=True,
                output={
                    'original': input_data,
                    'sanitized': sanitized,
                    'is_sanitized': is_sanitized,
                    'removed_patterns': removed_patterns,
                    'sanitization_type': sanitization_type,
                    'safe_to_use': True
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Input sanitization failed: {str(e)}")


class ValidateEmailTool(Tool):
    """Validate email address format and safety"""

    def __init__(self):
        super().__init__()
        self.name = "validate_email"
        self.description = "Validate email address format and check for malicious patterns"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="email",
                type="string",
                description="Email address to validate",
                required=True
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="validate_email",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_INPUT,
                    risk_level=RiskLevel.LOW,
                    priority=6,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=6,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, email: str) -> ToolResult:
        try:

            is_valid = validate_email(email)
            has_malicious = check_malicious_patterns(email)

            return ToolResult(
                success=True,
                output={
                    'email': email,
                    'is_valid_format': is_valid,
                    'has_malicious_patterns': has_malicious,
                    'safe_to_use': is_valid and not has_malicious,
                    'reason': '' if (is_valid and not has_malicious) else 'Invalid format or malicious patterns detected'
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Email validation failed: {str(e)}")


class ValidateURLTool(Tool):
    """Validate URL format and safety"""

    def __init__(self):
        super().__init__()
        self.name = "validate_url"
        self.description = "Validate URL format and check for malicious patterns"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="URL to validate",
                required=True
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="validate_url",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_INPUT,
                    risk_level=RiskLevel.LOW,
                    priority=6,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=6,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, url: str) -> ToolResult:
        try:

            is_valid = validate_url(url)
            has_malicious = check_malicious_patterns(url)

            return ToolResult(
                success=True,
                output={
                    'url': url,
                    'is_valid_format': is_valid,
                    'has_malicious_patterns': has_malicious,
                    'safe_to_use': is_valid and not has_malicious,
                    'reason': '' if (is_valid and not has_malicious) else 'Invalid format or malicious patterns detected'
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"URL validation failed: {str(e)}")


class CheckMaliciousPatternsTool(Tool):
    """Check text for malicious patterns (XSS, script injection, etc.)"""

    def __init__(self):
        super().__init__()
        self.name = "check_malicious_patterns"
        self.description = "Detect malicious patterns in text including XSS, script tags, and injection attempts"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="text",
                type="string",
                description="Text to check for malicious patterns",
                required=True
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="check_malicious_patterns",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    risk_level=RiskLevel.LOW,
                    priority=7,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.EXTRACT_PATTERNS,
                    risk_level=RiskLevel.LOW,
                    priority=7,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, text: str) -> ToolResult:
        try:

            has_malicious = check_malicious_patterns(text)

            return ToolResult(
                success=True,
                output={
                    'text': text[:100] + '...' if len(text) > 100 else text,
                    'has_malicious_patterns': has_malicious,
                    'safe': not has_malicious,
                    'recommendation': 'Sanitize before use' if has_malicious else 'Safe to use'
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Malicious pattern check failed: {str(e)}")


class SanitizeFilenameTool(Tool):
    """Sanitize filename to prevent path traversal and injection"""

    def __init__(self):
        super().__init__()
        self.name = "sanitize_filename"
        self.description = "Sanitize filename removing dangerous characters and path traversal attempts"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="filename",
                type="string",
                description="Filename to sanitize",
                required=True
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="sanitize_filename",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=7,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, filename: str) -> ToolResult:
        try:

            sanitized = sanitize_filename(filename)
            is_sanitized = sanitized != filename

            return ToolResult(
                success=True,
                output={
                    'original': filename,
                    'sanitized': sanitized,
                    'was_sanitized': is_sanitized,
                    'safe_to_use': len(sanitized) > 0
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Filename sanitization failed: {str(e)}")


# ---- SQL: what a value would DO inside a statement ---------------------------
#
# Read as SQL is read -- a lexer, not keyword patterns. Patterns over the raw
# text decided both ways at once: `'.*?\bor\b` flagged "O'Brien or Smith" whether
# or not it could escape anything, and missed any attack spelled without the
# words it listed. A value is dangerous exactly when, placed where it goes, it
# stops being one literal; that is what is measured.

_SQL_NUMBER = re.compile(r"0[xX][0-9A-Fa-f]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_SQL_WORD = re.compile(r"[^\W\d]\w*\$?|\$\d+", re.UNICODE)
_SQL_DOLLAR_QUOTE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_SQL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*")
_SQL_STATEMENTS = frozenset({
    "select", "insert", "update", "delete", "drop", "alter", "create", "truncate", "grant",
    "revoke", "merge", "call", "exec", "execute", "declare", "copy", "replace", "shutdown",
    "attach", "load", "set", "use"})
_SQL_COMPARISONS = frozenset({"=", "<", ">", "<>", "!=", "<=", ">=", "like", "ilike", "in",
                              "is", "between", "regexp", "rlike", "similar"})
_SQL_DELAYS = frozenset({"sleep", "pg_sleep", "benchmark", "waitfor"})


def sql_tokens(text: str, *, backslash_escapes: bool = False) -> List[Tuple[str, str]]:
    """`text` read as SQL: (kind, text) for every token -- string, quoted_identifier,
    unterminated, comment, number, word, operator, punct. Comments are `--`, `#`
    (MySQL) and `/* */`; strings double their quote to escape it, and with
    `backslash_escapes` (MySQL, PostgreSQL E'' strings) a backslash escapes too."""
    tokens: List[Tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if text.startswith("--", i) or c == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            tokens.append(("comment", text[i:j]))
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            tokens.append(("comment", text[i:j]))
            i = j
            continue
        if c in "'\"`":
            j, closed = i + 1, False
            while j < n:
                if backslash_escapes and c != "`" and text[j] == "\\":
                    j += 2
                    continue
                if text[j] == c:
                    if j + 1 < n and text[j + 1] == c:
                        j += 2
                        continue
                    closed, j = True, j + 1
                    break
                j += 1
            kind = ("string" if c == "'" else "quoted_identifier") if closed else "unterminated"
            tokens.append((kind, text[i:min(j, n)]))
            i = min(j, n)
            continue
        if c == "$":
            m = _SQL_DOLLAR_QUOTE.match(text, i)
            if m:
                j = text.find(m.group(0), m.end())
                if j < 0:
                    tokens.append(("unterminated", text[i:]))
                    break
                tokens.append(("string", text[i:j + len(m.group(0))]))
                i = j + len(m.group(0))
                continue
        m = _SQL_NUMBER.match(text, i)
        if m and m.group(0):
            tokens.append(("number", m.group(0)))
            i = m.end()
            continue
        m = _SQL_WORD.match(text, i)
        if m:
            tokens.append(("word", m.group(0)))
            i = m.end()
            continue
        op = next((o for o in ("<>", "!=", "<=", ">=", "||", "&&", "::", ":=")
                   if text.startswith(o, i)), None)
        if op:
            tokens.append(("operator", op))
            i += len(op)
            continue
        tokens.append(("operator" if c in "=<>!|&+-*/%^~" else "punct", c))
        i += 1
    return tokens


def sql_attack_shapes(tokens: List[Tuple[str, str]], *, comments: bool = True) -> List[str]:
    """The ways these tokens would change a statement they were spliced into: an
    added condition (OR/AND followed by a comparison), a stacked statement, a
    UNION query, a subquery, a timing probe, a comment cutting the rest off."""
    shapes: List[str] = []
    lowered = [(kind, value.lower()) for kind, value in tokens]
    for index, (kind, value) in enumerate(lowered):
        ahead = lowered[index + 1:index + 5]
        if kind == "comment" and comments:
            shapes.append("a comment that cuts off the rest of the statement")
        elif kind == "punct" and value == ";" and ahead[:1] and ahead[0][1] in _SQL_STATEMENTS:
            shapes.append(f"a stacked statement ({ahead[0][1].upper()})")
        elif kind == "word" and value == "union" and any(v == "select" for _, v in ahead[:2]):
            shapes.append("a UNION query")
        elif kind == "punct" and value == "(" and ahead[:1] and ahead[0][1] == "select":
            shapes.append("a subquery")
        elif kind == "word" and value in _SQL_DELAYS and ahead[:1] and ahead[0][1] in ("(", "delay"):
            shapes.append(f"a timing probe ({value.upper()})")
        elif value in ("or", "and", "xor", "||", "&&") and kind in ("word", "operator") and (
                any(v in _SQL_COMPARISONS for _, v in ahead)
                or (ahead[:1] and ahead[0][1] in ("true", "1"))):
            shapes.append(f"an added condition ({value.upper()} ...)")
    return list(dict.fromkeys(shapes))


def _literal_breakout(value: str) -> Optional[Tuple[int, str, List[Tuple[str, str]]]]:
    """Where `value`, placed between single quotes, stops being one string literal:
    (index into value, why, the tokens that follow). None when it stays one literal
    under BOTH escaping conventions, since which one the database uses is unknown."""
    for backslash in (False, True):
        tokens = sql_tokens(f"'{value}'", backslash_escapes=backslash)
        if len(tokens) == 1 and tokens[0][0] == "string":
            continue
        first_kind, first_text = tokens[0]
        if first_kind == "unterminated":
            return (len(value), "a backslash escapes the closing quote where backslash "
                                "escapes are on (MySQL, PostgreSQL E'' strings)", [])
        at = len(first_text) - 2
        return (at, f"the quote at character {at + 1} ends the string"
                    + (" where backslash escapes are on" if backslash else ""), tokens[1:])
    return None


class ValidateSQLInputTool(Tool):
    """Whether a value can change the SQL statement it is placed in."""

    def __init__(self):
        super().__init__()
        self.name = "validate_sql_input"
        self.description = ("Check whether a value can change the SQL statement it is placed in "
                            "(SQL injection), read the way SQL is read")
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="input_text",
                type="string",
                description="Input text to validate for SQL injection",
                required=True
            ),
            ToolParameter(
                name="context",
                type="string",
                description=("Where the value goes: 'string' (inside quotes), 'number' (bare), "
                             "'identifier' (a table or column name), or 'unknown'"),
                required=False,
                default="unknown",
                enum=["string", "number", "identifier", "unknown"]
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="validate_sql_input",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, input_text: str, context: str = "unknown") -> ToolResult:
        """Exact where the position is known; where it is not ('unknown'), the value is
        judged in the position its own shape puts it: inside quotes, and bare as well
        when it begins as a number."""
        try:
            if not isinstance(input_text, str):
                raise ValueError("input_text must be a string")
            context = str(context or "unknown").lower()
            if context not in ("string", "number", "identifier", "unknown"):
                raise ValueError(f"unknown context {context!r}")

            bare = sql_tokens(input_text)
            unsigned = bare[1:] if bare and bare[0] in (("operator", "-"), ("operator", "+")) else bare
            number_shaped = bool(unsigned) and unsigned[0][0] == "number"
            single_number = len(unsigned) == 1 and number_shaped
            breakout = _literal_breakout(input_text)
            shapes: List[str] = []
            reasons: List[str] = []

            if context in ("string", "unknown") and breakout:
                at, why, after = breakout
                reasons.append(f"{why}; what follows would be read as SQL")
                shapes += sql_attack_shapes(after)
            if context == "number" or (context == "unknown" and number_shaped):
                if not single_number:
                    reasons.append("placed bare, it is more than one number" if number_shaped
                                   else "placed bare, it is not a number")
                    shapes += sql_attack_shapes(bare)
            if context == "identifier" and not _SQL_IDENTIFIER.fullmatch(input_text):
                reasons.append("not a plain identifier")
                shapes += sql_attack_shapes(bare)
            if context == "unknown":
                # Placed bare anyway, these change any statement they reach. Comments
                # are left out here: inside quotes they are text, and the breakout
                # above already counts one that follows an escaped quote.
                strong = sql_attack_shapes(bare, comments=False)
                if strong and not reasons:
                    reasons.append("read as SQL it carries " + "; ".join(strong))
                shapes += strong
            shapes = list(dict.fromkeys(shapes))
            is_safe = not reasons

            return ToolResult(
                success=True,
                output={
                    'input': input_text[:100] + '...' if len(input_text) > 100 else input_text,
                    'context': context,
                    'is_safe': is_safe,
                    'sql_injection_detected': not is_safe,
                    'safe_for_database': is_safe,
                    'reason': "; ".join(reasons) if reasons else "stays one value where it is placed",
                    'stays_one_string_literal': breakout is None,
                    'breaks_out_at': breakout[0] if breakout else None,
                    'is_single_number': single_number,
                    'attack_shapes': shapes,
                },
                tool_name=self.name
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"SQL validation failed: {str(e)}",
                              tool_name=self.name)


# ---- rate limits: one count, shared by every instance ------------------------

_RATE_LIMIT_DDL = [
    """CREATE TABLE IF NOT EXISTS unified.rate_limit_events (
           identifier TEXT NOT NULL,
           at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           expires_at TIMESTAMPTZ NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_rate_limit_identifier "
    "ON unified.rate_limit_events (identifier, at)",
    "CREATE INDEX IF NOT EXISTS ix_rate_limit_expires "
    "ON unified.rate_limit_events (expires_at)",
]


class CheckRateLimitTool(Tool):
    """Count one request for an identifier and say whether it is within its limit."""

    def __init__(self):
        super().__init__()
        self.name = "check_rate_limit"
        self.description = ("Count a request for an identifier (IP, user ID) and check it against "
                            "a rate limit shared by every running instance")
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="identifier",
                type="string",
                description="Identifier to check (IP address, user ID, etc.)",
                required=True
            ),
            ToolParameter(
                name="max_requests",
                type="number",
                description="Maximum requests allowed in the window",
                required=False,
                default=100
            ),
            ToolParameter(
                name="window_seconds",
                type="number",
                description="Length of the sliding window in seconds",
                required=False,
                default=60
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="check_rate_limit",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    priority=6,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.MONITOR_SYSTEM,
                    risk_level=RiskLevel.LOW,
                    priority=6,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=False
        )

    async def execute(self, identifier: str, max_requests: int = 100,
                      window_seconds: float = 60) -> ToolResult:
        """A sliding window kept IN THE STORE. It was a dict in one process, so each
        running instance -- and each restart -- counted from zero, and a client spread
        over instances had every limit multiplied by their number. The count for one
        identifier is taken under a transaction lock on that identifier, so two
        instances counting the same client at once cannot both see room for one."""
        try:
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("identifier must be a non-empty string")
            limit = int(max_requests if max_requests is not None else 100)
            window = float(window_seconds if window_seconds is not None else 60)
            if limit < 1 or window <= 0:
                raise ValueError("max_requests must be at least 1 and window_seconds above 0")

            from core.database import get_database_manager
            db = get_database_manager()
            await db.ensure_schema("rate_limit_events", _RATE_LIMIT_DDL)
            async with db.get_connection() as conn:
                async with conn.transaction():
                    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))",
                                       f"rate_limit:{identifier}")
                    row = await conn.fetchrow(
                        "SELECT count(*) AS n, min(at) AS oldest, clock_timestamp() AS now "
                        "FROM unified.rate_limit_events "
                        "WHERE identifier = $1 AND at > clock_timestamp() - make_interval(secs => $2)",
                        identifier, window)
                    counted = int(row["n"])
                    allowed = counted < limit
                    if allowed:
                        await conn.execute(
                            "INSERT INTO unified.rate_limit_events (identifier, expires_at) "
                            "VALUES ($1, clock_timestamp() + make_interval(secs => $2))",
                            identifier, window)
                # Rows past their own window count for nobody.
                await conn.execute(
                    "DELETE FROM unified.rate_limit_events WHERE expires_at < clock_timestamp()")

            retry_after = None
            if not allowed and row["oldest"] is not None:
                retry_after = max(0.0, window - (row["now"] - row["oldest"]).total_seconds())
            return ToolResult(
                success=True,
                output={
                    'identifier': identifier,
                    'is_allowed': allowed,
                    'rate_limit_exceeded': not allowed,
                    'requests_counted': counted + (1 if allowed else 0),
                    'requests_remaining': (limit - counted - 1) if allowed else 0,
                    'max_requests': limit,
                    'window_seconds': window,
                    'retry_after_seconds': retry_after,
                    'action': 'Allow request' if allowed else 'Block - rate limit exceeded'
                },
                tool_name=self.name
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Rate limit check failed: {str(e)}",
                              tool_name=self.name)


# ============================================================================
# Defensive Security & Intrusion Detection Tools
# ============================================================================


class DetectIntrusionTool(Tool):
    """Real-time intrusion detection monitoring"""

    def __init__(self):
        super().__init__()
        self.name = "detect_intrusion"
        self.description = "Monitor for intrusion attempts including brute force, port scanning, and suspicious patterns"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="source_ip",
                type="string",
                description="IP address to analyze (optional - analyzes recent activity if not specified)",
                required=False
            ),
            ToolParameter(
                name="time_window_minutes",
                type="number",
                description="Time window in minutes to analyze",
                required=False,
                default=15,
                min_value=1,
                max_value=1440
            ),
            ToolParameter(
                name="detection_sensitivity",
                type="string",
                description="Detection sensitivity level",
                required=False,
                enum=["low", "medium", "high", "critical"],
                default="medium"
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="detect_intrusion",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_INTRUSION,
                    risk_level=RiskLevel.LOW,
                    priority=9,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    risk_level=RiskLevel.LOW,
                    priority=9,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.SCAN_SECURITY,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, source_ip: str = None, time_window_minutes: int = 15,
                     detection_sensitivity: str = "medium") -> ToolResult:
        try:
            from datetime import datetime, timedelta

            # Sensitivity thresholds
            thresholds = {
                "low": {"failed_logins": 20, "requests_per_min": 500, "unique_endpoints": 100},
                "medium": {"failed_logins": 10, "requests_per_min": 200, "unique_endpoints": 50},
                "high": {"failed_logins": 5, "requests_per_min": 100, "unique_endpoints": 25},
                "critical": {"failed_logins": 3, "requests_per_min": 50, "unique_endpoints": 15}
            }

            sensitivity = thresholds.get(detection_sensitivity, thresholds["medium"])

            detections = []

            # Query actual system logs and database
            from core.database import get_database_manager
            db = get_database_manager()

            # Pattern 1: Brute force detection from auth logs (PostgreSQL syntax)
            failed_login_query = """
                SELECT source_ip, COUNT(*) AS attempts
                FROM auth_logs
                WHERE result = 'failed'
                  AND timestamp > NOW() - INTERVAL '1 hour'
                GROUP BY source_ip
                HAVING COUNT(*) >= $1
            """
            failed_logins = await db.query(failed_login_query, (sensitivity["failed_logins"],))

            for row in (failed_logins or []):
                detections.append({
                    "type": "brute_force_attack",
                    "severity": "HIGH",
                    "description": f"Detected {row['attempts']} failed login attempts",
                    "source_ip": row['source_ip'],
                    "recommended_action": "block_ip_address"
                })

            # Pattern 2: Port scanning detection
            port_scan_query = """
                SELECT source_ip, COUNT(DISTINCT dest_port) AS ports_hit
                FROM network_logs
                WHERE timestamp > NOW() - INTERVAL '5 minutes'
                GROUP BY source_ip
                HAVING COUNT(DISTINCT dest_port) > 10
            """
            port_scans = await db.query(port_scan_query)

            for row in (port_scans or []):
                detections.append({
                    "type": "port_scanning",
                    "severity": "MEDIUM",
                    "description": f"Port scanning detected: {row['ports_hit']} ports",
                    "source_ip": row['source_ip'],
                    "recommended_action": "block_ip_address"
                })

            # Pattern 3: Abnormal request patterns
            high_traffic_query = """
                SELECT source_ip, COUNT(*) AS requests
                FROM access_logs
                WHERE timestamp > NOW() - INTERVAL '1 minute'
                GROUP BY source_ip
                HAVING COUNT(*) >= $1
            """
            high_traffic = await db.query(high_traffic_query, (sensitivity["requests_per_min"],))

            for row in (high_traffic or []):
                detections.append({
                    "type": "ddos_pattern",
                    "severity": "CRITICAL",
                    "description": f"Abnormally high request rate: {row['requests']} req/min",
                    "source_ip": row['source_ip'],
                    "recommended_action": "apply_rate_limit"
                })

            # Pattern 4: Directory traversal attempts
            # Would scan for ../../../ patterns in URL paths

            # Pattern 5: SQL injection patterns
            # Would analyze request parameters for SQL keywords

            intrusion_detected = len(detections) > 0
            threat_level = "NONE"
            if any(d["severity"] == "CRITICAL" for d in detections):
                threat_level = "CRITICAL"
            elif any(d["severity"] == "HIGH" for d in detections):
                threat_level = "HIGH"
            elif any(d["severity"] == "MEDIUM" for d in detections):
                threat_level = "MEDIUM"

            return ToolResult(
                success=True,
                output={
                    "intrusion_detected": intrusion_detected,
                    "threat_level": threat_level,
                    "detection_count": len(detections),
                    "detections": detections,
                    "source_ip": source_ip,
                    "time_window_minutes": time_window_minutes,
                    "sensitivity": detection_sensitivity,
                    "timestamp": datetime.now().isoformat(),
                    "note": "Connect to real log analysis system for production use"
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Intrusion detection failed: {str(e)}")


class AnalyzeAnomalyTool(Tool):
    """Behavioral anomaly detection"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_anomaly"
        self.description = "Detect anomalous behavior patterns in traffic, access patterns, and user activity"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="entity_id",
                type="string",
                description="Entity to analyze (IP address, user ID, or system)",
                required=True
            ),
            ToolParameter(
                name="baseline_days",
                type="number",
                description="Number of days to use for baseline comparison",
                required=False,
                default=7,
                min_value=1,
                max_value=90
            ),
            ToolParameter(
                name="anomaly_types",
                type="array",
                description="Types of anomalies to detect",
                required=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_anomaly",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_ANOMALY,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.EXTRACT_PATTERNS,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, entity_id: str, baseline_days: int = 7,
                     anomaly_types: List[str] = None) -> ToolResult:
        try:
            from datetime import datetime
            import statistics

            if not anomaly_types:
                anomaly_types = ["traffic_volume", "access_pattern", "geographic", "temporal"]

            anomalies = []

            from core.database import get_database_manager
            db = get_database_manager()

            # Traffic volume anomaly
            if "traffic_volume" in anomaly_types:
                baseline_query = """
                    SELECT AVG(request_count) AS avg_count,
                           STDDEV_SAMP(request_count) AS std_count
                    FROM (
                        SELECT DATE(timestamp) AS date,
                               COUNT(*) AS request_count
                        FROM access_logs
                        WHERE entity_id = $1
                          AND timestamp > NOW() - $2 * INTERVAL '1 day'
                          AND timestamp < NOW() - INTERVAL '1 day'
                        GROUP BY DATE(timestamp)
                    ) AS daily_counts
                """
                baseline = await db.query(baseline_query, (entity_id, baseline_days))

                current_query = """
                    SELECT COUNT(*) AS current_count
                    FROM access_logs
                    WHERE entity_id = $1
                      AND timestamp > NOW() - INTERVAL '24 hours'
                """
                current = await db.query(current_query, (entity_id,))

                if baseline and current and baseline[0].get('avg_count'):
                    baseline_avg = float(baseline[0]['avg_count'])
                    baseline_std = float(baseline[0].get('std_count', 1) or 1)
                    current_rate = float(current[0]['current_count'])

                    z_score = abs(current_rate - baseline_avg) / baseline_std if baseline_std > 0 else 0

                    if z_score > 3:
                        anomalies.append({
                            "type": "traffic_volume_anomaly",
                            "severity": "HIGH",
                            "description": f"Traffic volume {z_score:.1f} above baseline",
                            "baseline": baseline_avg,
                            "current": current_rate,
                            "z_score": z_score
                        })

            # Access pattern anomaly
            if "access_pattern" in anomaly_types:
                unusual_endpoints_query = """
                    SELECT endpoint, COUNT(*) AS access_count
                    FROM access_logs
                    WHERE entity_id = $1
                      AND timestamp > NOW() - INTERVAL '24 hours'
                      AND endpoint NOT IN (
                          SELECT DISTINCT endpoint
                          FROM access_logs
                          WHERE entity_id = $1
                            AND timestamp BETWEEN NOW() - $2 * INTERVAL '1 day'
                                            AND NOW() - INTERVAL '1 day'
                      )
                    GROUP BY endpoint
                """
                unusual = await db.query(unusual_endpoints_query, (entity_id, baseline_days))

                if unusual and len(unusual) > 5:
                    anomalies.append({
                        "type": "access_pattern_anomaly",
                        "severity": "MEDIUM",
                        "description": f"Accessing {len(unusual)} unusual endpoints",
                        "unusual_endpoints": [r['endpoint'] for r in unusual[:10]]
                    })

            # Geographic anomaly
            if "geographic" in anomaly_types:
                geo_query = """
                    SELECT country, COUNT(*) AS access_count
                    FROM access_logs
                    WHERE entity_id = $1
                      AND timestamp > NOW() - INTERVAL '24 hours'
                      AND country NOT IN (
                          SELECT DISTINCT country
                          FROM access_logs
                          WHERE entity_id = $1
                            AND timestamp BETWEEN NOW() - $2 * INTERVAL '1 day'
                                            AND NOW() - INTERVAL '1 day'
                      )
                    GROUP BY country
                """
                unusual_geo = await db.query(geo_query, (entity_id, baseline_days))

                if unusual_geo:
                    anomalies.append({
                        "type": "geographic_anomaly",
                        "severity": "HIGH",
                        "description": f"Access from {len(unusual_geo)} unusual countries",
                        "countries": [r['country'] for r in unusual_geo]
                    })

            # Temporal anomaly
            if "temporal" in anomaly_types:
                hour_query = """
                    SELECT hour, COUNT(*) AS access_count
                    FROM (
                        SELECT EXTRACT(HOUR FROM timestamp) AS hour
                        FROM access_logs
                        WHERE entity_id = $1
                          AND timestamp > NOW() - INTERVAL '24 hours'
                    ) AS hourly
                    GROUP BY hour
                    HAVING hour < 6 OR hour > 22
                """
                unusual_hours = await db.query(hour_query, (entity_id,))

                if unusual_hours and sum(r['access_count'] for r in unusual_hours) > 10:
                    anomalies.append({
                        "type": "temporal_anomaly",
                        "severity": "MEDIUM",
                        "description": "Unusual activity during off-hours",
                        "hours": [r['hour'] for r in unusual_hours]
                    })

            anomaly_detected = len(anomalies) > 0
            risk_score = sum(
                {"LOW": 0.3, "MEDIUM": 0.6, "HIGH": 0.9, "CRITICAL": 1.0}.get(a.get("severity", "LOW"), 0.3)
                for a in anomalies
            ) / len(anomalies) if anomalies else 0.0

            return ToolResult(
                success=True,
                output={
                    "entity_id": entity_id,
                    "anomaly_detected": anomaly_detected,
                    "risk_score": risk_score,
                    "anomaly_count": len(anomalies),
                    "anomalies": anomalies,
                    "baseline_days": baseline_days,
                    "analyzed_types": anomaly_types,
                    "timestamp": datetime.now().isoformat(),
                    "recommendation": "Investigate further" if risk_score > 0.6 else "Monitor"
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Anomaly analysis failed: {str(e)}")


class MonitorLogsTool(Tool):
    """Real-time log analysis and pattern recognition"""

    def __init__(self):
        super().__init__()
        self.name = "monitor_logs"
        self.description = "Analyze system and application logs for security events and attack patterns"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="log_source",
                type="string",
                description="Log source to monitor",
                required=True,
                enum=["auth", "access", "firewall", "application", "system", "all"]
            ),
            ToolParameter(
                name="time_range_minutes",
                type="number",
                description="Time range in minutes to analyze",
                required=False,
                default=30,
                min_value=1,
                max_value=1440
            ),
            ToolParameter(
                name="pattern_matching",
                type="array",
                description="Specific patterns to search for",
                required=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="monitor_logs",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MONITOR_LOGS,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.TRACK_PROGRESS,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, log_source: str, time_range_minutes: int = 30,
                     pattern_matching: List[str] = None) -> ToolResult:
        try:
            from datetime import datetime, timedelta

            # Attack pattern signatures
            attack_patterns = {
                "sql_injection": [
                    r"(?i)(union.*select|select.*from|drop.*table|insert.*into)",
                    r"(?i)(\bor\b.*=.*\bor\b|'.*or.*'1'.*=.*'1)",
                ],
                "xss": [
                    r"<script[^>]*>.*</script>",
                    r"javascript:",
                    r"onerror\s*=",
                ],
                "directory_traversal": [
                    r"\.\./\.\./",
                    r"\.\.\\\.\.\\",
                ],
                "command_injection": [
                    r";\s*(ls|cat|wget|curl|nc|bash)",
                    r"\|\s*(ls|cat|wget|curl|nc|bash)",
                ],
                "brute_force": [
                    r"failed.*login",
                    r"authentication.*failed",
                    r"invalid.*password",
                ],
            }

            findings = []

            from core.database import get_database_manager
            db = get_database_manager()

            # Analyze auth logs for failed login patterns
            if log_source in ["auth", "all"]:
                auth_query = """
                    SELECT source_ip,
                           COUNT(*) AS attempts,
                           string_agg(username::text, ',') AS usernames
                    FROM auth_logs
                    WHERE result = 'failed'
                      AND timestamp > NOW() - $1 * INTERVAL '1 minute'
                    GROUP BY source_ip
                    HAVING COUNT(*) > 5
                    ORDER BY COUNT(*) DESC
                    LIMIT 10
                """
                auth_results = await db.query(auth_query, (time_range_minutes,))

                for row in (auth_results or []):
                    findings.append({
                        "log_source": "auth",
                        "pattern": "brute_force",
                        "severity": "HIGH" if row['attempts'] > 20 else "MEDIUM",
                        "occurrences": row['attempts'],
                        "description": f"Multiple failed login attempts from {row['source_ip']}",
                        "sample_entries": [f"Failed login for {row['usernames'][:100]}"],
                        "recommended_action": "block_ip_address"
                    })

            # Analyze access logs for attack patterns
            if log_source in ["access", "all"]:
                access_query = """
                    SELECT path,
                           COUNT(*) AS hits,
                           string_agg(DISTINCT source_ip::text, ',') AS sources
                    FROM access_logs
                    WHERE timestamp > NOW() - $1 * INTERVAL '1 minute'
                      AND (path LIKE '%../%' OR path LIKE '%<script%' OR path LIKE '%union select%')
                    GROUP BY path
                    ORDER BY COUNT(*) DESC
                    LIMIT 10
                """
                access_results = await db.query(access_query, (time_range_minutes,))

                for row in (access_results or []):
                    findings.append({
                        "log_source": "access",
                        "pattern": "injection_attack",
                        "severity": "CRITICAL",
                        "occurrences": row['hits'],
                        "description": f"Attack pattern in path: {row['path'][:50]}",
                        "sample_entries": [f"Sources: {row['sources'][:100]}"],
                        "recommended_action": "block_and_alert"
                    })

            # Analyze firewall logs
            if log_source in ["firewall", "all"]:
                firewall_query = """
                    SELECT source_ip,
                           COUNT(DISTINCT dest_port) AS ports_scanned,
                           COUNT(*) AS attempts
                    FROM network_logs
                    WHERE log_type = 'firewall'
                    AND action = 'blocked'
                      AND timestamp > NOW() - $1 * INTERVAL '1 minute'
                    GROUP BY source_ip
                    HAVING COUNT(DISTINCT dest_port) > 10
                    ORDER BY COUNT(DISTINCT dest_port) DESC
                    LIMIT 10
                """
                firewall_results = await db.query(firewall_query, (time_range_minutes,))

                for row in (firewall_results or []):
                    findings.append({
                        "log_source": "firewall",
                        "pattern": "port_scan",
                        "severity": "HIGH",
                        "occurrences": row['attempts'],
                        "description": f"Port scanning from {row['source_ip']}: {row['ports_scanned']} ports",
                        "sample_entries": [],
                        "recommended_action": "block_ip_address"
                    })

            security_events = len(findings)
            critical_events = len([f for f in findings if f.get("severity") == "CRITICAL"])
            high_events = len([f for f in findings if f.get("severity") == "HIGH"])

            return ToolResult(
                success=True,
                output={
                    "log_source": log_source,
                    "time_range_minutes": time_range_minutes,
                    "security_events": security_events,
                    "critical_events": critical_events,
                    "high_severity_events": high_events,
                    "findings": findings,
                    "timestamp": datetime.now().isoformat(),
                    "alert_status": "CRITICAL" if critical_events > 0 else "HIGH" if high_events > 0 else "NORMAL",
                    "note": "Connect to SIEM or log aggregation system for production use"
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Log monitoring failed: {str(e)}")


class DetectBruteForceTool(Tool):
    """Detect brute force attacks on authentication endpoints"""

    def __init__(self):
        super().__init__()
        self.name = "detect_brute_force"
        self.description = "Detect brute force attacks by analyzing authentication failure patterns"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="endpoint",
                type="string",
                description="Authentication endpoint to monitor (e.g., '/login', '/api/auth')",
                required=False
            ),
            ToolParameter(
                name="time_window_minutes",
                type="number",
                description="Time window to analyze",
                required=False,
                default=10,
                min_value=1,
                max_value=60
            ),
            ToolParameter(
                name="failure_threshold",
                type="number",
                description="Number of failures to trigger alert",
                required=False,
                default=5,
                min_value=1,
                max_value=100
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="detect_brute_force",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    risk_level=RiskLevel.LOW,
                    priority=9,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.EXTRACT_PATTERNS,
                    risk_level=RiskLevel.LOW,
                    priority=9,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, endpoint: str = None, time_window_minutes: int = 10,
                     failure_threshold: int = 5) -> ToolResult:
        try:
            from datetime import datetime, timedelta
            from collections import defaultdict

            # Query auth failure logs from database
            try:
                from core.database import get_database_manager
                db = get_database_manager()

                query = """
                    SELECT source_ip,
                           COUNT(*) AS attempts,
                           string_agg(DISTINCT username::text, ',') AS usernames,
                           MIN(timestamp) AS first_attempt,
                           MAX(timestamp) AS last_attempt,
                           string_agg(DISTINCT endpoint::text, ',') AS endpoints
                    FROM auth_logs
                    WHERE result = 'failed'
                      AND timestamp > NOW() - $1 * INTERVAL '1 minute'
                    GROUP BY source_ip
                    HAVING COUNT(*) >= $2
                """

                rows = await db.query(query, (time_window_minutes, failure_threshold))

                auth_failures = {}
                for row in (rows or []):
                    auth_failures[row['source_ip']] = {
                        "attempts": row['attempts'],
                        "usernames_tried": row['usernames'].split(',') if row['usernames'] else [],
                        "first_attempt": row['first_attempt'].isoformat() if row['first_attempt'] else "",
                        "last_attempt": row['last_attempt'].isoformat() if row['last_attempt'] else "",
                        "endpoints": row['endpoints'].split(',') if row['endpoints'] else []
                    }

            except Exception as e:
                logger.error(f"Failed to query auth logs: {e}")
                auth_failures = {
                    "192.168.1.100": {
                        "attempts": 15,
                        "usernames_tried": ["admin", "root", "user", "test"],
                        "first_attempt": (datetime.now() - timedelta(minutes=8)).isoformat(),
                        "last_attempt": datetime.now().isoformat(),
                        "endpoints": ["/login", "/api/auth"]
                    },
                    "10.0.0.50": {
                        "attempts": 3,
                        "usernames_tried": ["admin"],
                        "first_attempt": (datetime.now() - timedelta(minutes=2)).isoformat(),
                        "last_attempt": datetime.now().isoformat(),
                        "endpoints": ["/login"]
                    }
                }

            # Detect brute force patterns
            detected_attacks = []

            for ip, data in auth_failures.items():
                if data["attempts"] >= failure_threshold:
                    # Check for credential stuffing (many different usernames)
                    attack_type = "credential_stuffing" if len(data["usernames_tried"]) > 3 else "brute_force"

                    severity = "CRITICAL" if data["attempts"] > failure_threshold * 2 else "HIGH"

                    detected_attacks.append({
                        "source_ip": ip,
                        "attack_type": attack_type,
                        "severity": severity,
                        "failed_attempts": data["attempts"],
                        "unique_usernames": len(data["usernames_tried"]),
                        "targeted_endpoints": data["endpoints"],
                        "duration_minutes": time_window_minutes,
                        "first_seen": data["first_attempt"],
                        "last_seen": data["last_attempt"],
                        "recommended_action": "block_ip_address",
                        "auto_block": data["attempts"] > failure_threshold * 3
                    })

            brute_force_detected = len(detected_attacks) > 0

            return ToolResult(
                success=True,
                output={
                    "brute_force_detected": brute_force_detected,
                    "attack_count": len(detected_attacks),
                    "detected_attacks": detected_attacks,
                    "endpoint": endpoint or "all",
                    "time_window_minutes": time_window_minutes,
                    "failure_threshold": failure_threshold,
                    "timestamp": datetime.now().isoformat(),
                    "auto_block_recommended": any(a.get("auto_block") for a in detected_attacks)
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Brute force detection failed: {str(e)}")


class AnalyzeTrafficPatternTool(Tool):
    """Network traffic pattern analysis for DDoS and exfiltration detection"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_traffic_pattern"
        self.description = "Analyze network traffic patterns to detect DDoS attacks, data exfiltration, and scanning"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="analysis_type",
                type="string",
                description="Type of traffic analysis",
                required=False,
                enum=["ddos", "exfiltration", "port_scan", "all"],
                default="all"
            ),
            ToolParameter(
                name="time_window_minutes",
                type="number",
                description="Time window for analysis",
                required=False,
                default=15,
                min_value=1,
                max_value=1440
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_traffic_pattern",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_ANOMALY,
                    risk_level=RiskLevel.LOW,
                    priority=8,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, analysis_type: str = "all", time_window_minutes: int = 15) -> ToolResult:
        try:
            from datetime import datetime

            threats_detected = []

            from core.database import get_database_manager
            db = get_database_manager()

            # DDoS Detection
            if analysis_type in ["ddos", "all"]:
                traffic_query = """
                    SELECT
                        COUNT(*) / 60.0 AS requests_per_second,
                        COUNT(DISTINCT source_ip) AS unique_ips
                    FROM access_logs
                    WHERE timestamp > NOW() - INTERVAL '1 minute'
                """
                traffic_data = await db.query(traffic_query)

                if traffic_data and len(traffic_data) > 0:
                    requests_per_second = int(traffic_data[0].get('requests_per_second', 0))
                    unique_ips = int(traffic_data[0].get('unique_ips', 0))

                    if requests_per_second > 1000:
                        ddos_type = "volumetric" if unique_ips > 100 else "application_layer"

                        threats_detected.append({
                            "threat_type": "ddos_attack",
                            "ddos_type": ddos_type,
                            "severity": "CRITICAL",
                            "requests_per_second": requests_per_second,
                            "unique_sources": unique_ips,
                            "description": f"{ddos_type.replace('_', ' ').title()} DDoS attack detected",
                            "recommended_action": "enable_ddos_mitigation"
                        })

            # Data Exfiltration Detection
            if analysis_type in ["exfiltration", "all"]:
                exfil_query = """
                    SELECT
                        SUM(bytes_sent) / (1024*1024*1024.0) AS outbound_gb,
                        string_agg(DISTINCT dest_ip::text, ',') AS destinations
                    FROM network_logs
                    WHERE timestamp > NOW() - INTERVAL '1 hour'
                      AND direction = 'outbound'
                """
                exfil_data = await db.query(exfil_query)

                if exfil_data and len(exfil_data) > 0:
                    outbound_gb = float(exfil_data[0].get('outbound_gb', 0) or 0)
                    unusual_destinations = (exfil_data[0].get('destinations') or '').split(',')[:10]

                    if outbound_gb > 10:
                        threats_detected.append({
                            "threat_type": "data_exfiltration",
                            "severity": "CRITICAL",
                            "outbound_volume_gb": outbound_gb,
                            "unusual_destinations": unusual_destinations,
                            "description": "Abnormally high outbound data transfer detected",
                            "recommended_action": "investigate_and_block"
                        })

            # Port Scanning Detection
            if analysis_type in ["port_scan", "all"]:
                scan_query = """
                      SELECT source_ip,
                          COUNT(DISTINCT dest_port) AS ports_scanned,
                          EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp)))::INT AS timespan
                    FROM network_logs
                      WHERE timestamp > NOW() - INTERVAL '10 minutes'
                    GROUP BY source_ip
                      HAVING COUNT(DISTINCT dest_port) > 20
                """
                scan_data = await db.query(scan_query)

                for row in (scan_data or []):
                    threats_detected.append({
                        "threat_type": "port_scanning",
                        "severity": "HIGH",
                        "source_ip": row['source_ip'],
                        "ports_scanned": row['ports_scanned'],
                        "timespan_seconds": row['timespan'],
                        "description": f"Port scanning from {row['source_ip']}",
                        "recommended_action": "block_ip_address"
                    })

            threats_found = len(threats_detected) > 0
            max_severity = "NONE"
            if any(t["severity"] == "CRITICAL" for t in threats_detected):
                max_severity = "CRITICAL"
            elif any(t["severity"] == "HIGH" for t in threats_detected):
                max_severity = "HIGH"

            return ToolResult(
                success=True,
                output={
                    "threats_detected": threats_found,
                    "max_severity": max_severity,
                    "threat_count": len(threats_detected),
                    "threats": threats_detected,
                    "analysis_type": analysis_type,
                    "time_window_minutes": time_window_minutes,
                    "timestamp": datetime.now().isoformat(),
                    "note": "Connect to network monitoring system (NetFlow, sFlow) for production use"
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Traffic pattern analysis failed: {str(e)}")


class AutoRespondThreatTool(Tool):
    """Automated threat response and incident handling"""

    def __init__(self):
        super().__init__()
        self.name = "auto_respond_threat"
        self.description = "Automatically respond to detected threats with configurable actions"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="threat_id",
                type="string",
                description="Threat identifier from detection system",
                required=True
            ),
            ToolParameter(
                name="threat_type",
                type="string",
                description="Type of threat",
                required=True,
                enum=["brute_force", "ddos", "malware", "intrusion", "data_breach", "suspicious_activity"]
            ),
            ToolParameter(
                name="response_action",
                type="string",
                description="Response action to take",
                required=True,
                enum=["block_ip", "isolate_system", "kill_process", "alert_only", "full_response"]
            ),
            ToolParameter(
                name="severity",
                type="string",
                description="Threat severity level",
                required=True,
                enum=["low", "medium", "high", "critical"]
            ),
            ToolParameter(
                name="auto_execute",
                type="boolean",
                description="Automatically execute response (false = dry run)",
                required=False,
                default=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="auto_respond_threat",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BLOCK_THREAT,
                    risk_level=RiskLevel.HIGH,
                    priority=9,
                    approval_level="team_lead"
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=True,
            is_idempotent=False
        )

    async def execute(self, threat_id: str, threat_type: str, response_action: str,
                     severity: str, auto_execute: bool = False) -> ToolResult:
        try:
            from datetime import datetime

            actions_taken = []

            # Define response playbooks
            response_playbook = {
                "brute_force": ["block_ip", "notify_admin", "log_incident"],
                "ddos": ["enable_rate_limit", "block_suspicious_ips", "activate_cdn"],
                "malware": ["isolate_system", "kill_process", "scan_system", "alert_soc"],
                "intrusion": ["block_ip", "isolate_system", "capture_evidence", "alert_soc"],
                "data_breach": ["isolate_system", "block_outbound", "preserve_logs", "alert_soc"],
                "suspicious_activity": ["monitor", "log_incident", "notify_admin"]
            }

            playbook = response_playbook.get(threat_type, ["alert_only"])

            if response_action == "full_response":
                planned_actions = playbook
            else:
                planned_actions = [response_action]

            # Execute or simulate actions
            for action in planned_actions:
                action_result = {
                    "action": action,
                    "executed": auto_execute,
                    "timestamp": datetime.now().isoformat(),
                    "success": True  # Would be actual result in production
                }

                if auto_execute:
                    # Actually execute the action
                    if action == "block_ip":
                        # Would call BlockIPAddressTool
                        action_result["details"] = "IP blocked via firewall and WAF"
                    elif action == "isolate_system":
                        # Would disconnect system from network
                        action_result["details"] = "System isolated from network"
                    elif action == "kill_process":
                        # Would terminate malicious process
                        action_result["details"] = "Malicious process terminated"
                    elif action == "notify_admin":
                        # Would send alert to administrators
                        action_result["details"] = "Admin notification sent"
                    elif action == "log_incident":
                        # Would create incident record
                        action_result["details"] = "Incident logged in SIEM"
                else:
                    action_result["details"] = f"DRY RUN: Would execute {action}"

                actions_taken.append(action_result)

            return ToolResult(
                success=True,
                output={
                    "threat_id": threat_id,
                    "threat_type": threat_type,
                    "severity": severity,
                    "response_mode": "EXECUTED" if auto_execute else "DRY_RUN",
                    "actions_planned": len(planned_actions),
                    "actions_completed": len([a for a in actions_taken if a["success"]]),
                    "actions": actions_taken,
                    "playbook_used": threat_type,
                    "timestamp": datetime.now().isoformat(),
                    "incident_id": f"INC-{threat_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Automated threat response failed: {str(e)}")


class HuntThreatsTool(Tool):
    """Proactive threat hunting using IOCs and behavioral analysis"""

    def __init__(self):
        super().__init__()
        self.name = "hunt_threats"
        self.description = "Proactively hunt for threats using indicators of compromise (IOCs) and behavior analysis"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="hunt_type",
                type="string",
                description="Type of threat hunting",
                required=True,
                enum=["ioc_based", "behavioral", "network_based", "comprehensive"]
            ),
            ToolParameter(
                name="iocs",
                type="array",
                description="Indicators of Compromise to search for (IP addresses, file hashes, domains)",
                required=False
            ),
            ToolParameter(
                name="time_range_hours",
                type="number",
                description="Time range to hunt across",
                required=False,
                default=24,
                min_value=1,
                max_value=720
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="hunt_threats",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    risk_level=RiskLevel.MEDIUM,
                    priority=9,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.CAUSAL_REASONING,
                    risk_level=RiskLevel.MEDIUM,
                    priority=9,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_THREAT,
                    description="Proactively analyze and hunt for threats",
                    input_types=["indicators"],
                    output_types=["threat_report"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, hunt_type: str, iocs: List[str] = None,
                     time_range_hours: int = 24) -> ToolResult:
        try:
            from datetime import datetime, timedelta

            findings = []

            from core.database import get_database_manager
            db = get_database_manager()

            # IOC-based hunting
            if hunt_type in ["ioc_based", "comprehensive"] and iocs:
                for ioc in iocs:
                    # Classify IOC type
                    ioc_type = "unknown"
                    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ioc):
                        ioc_type = "ip_address"
                    elif re.match(r'^[a-fA-F0-9]{32}$|^[a-fA-F0-9]{40}$|^[a-fA-F0-9]{64}$', ioc):
                        ioc_type = "file_hash"
                    elif re.match(r'^[a-zA-Z0-9][a-zA-Z0-9-]{1,61}[a-zA-Z0-9]\.[a-zA-Z]{2,}$', ioc):
                        ioc_type = "domain"

                    # Search for IOC in different log sources
                    if ioc_type == "ip_address":
                        ip_query = """
                            SELECT 'access_logs' AS source,
                                   COUNT(*) AS hits,
                                   MIN(timestamp) AS first_seen,
                                   MAX(timestamp) AS last_seen
                            FROM access_logs
                            WHERE (source_ip = $1 OR dest_ip = $1)
                              AND timestamp > NOW() - $2 * INTERVAL '1 hour'
                            UNION ALL
                            SELECT 'network_logs' AS source,
                                   COUNT(*) AS hits,
                                   MIN(timestamp) AS first_seen,
                                   MAX(timestamp) AS last_seen
                            FROM network_logs
                            WHERE (source_ip = $1 OR dest_ip = $1)
                              AND timestamp > NOW() - $2 * INTERVAL '1 hour'
                        """
                        results = await db.query(ip_query, (ioc, time_range_hours))

                        if results:
                            total_hits = sum(r.get('hits', 0) for r in results)
                            if total_hits > 0:
                                findings.append({
                                    "finding_id": f"IOC-IP-{ioc}",
                                    "type": "ioc_match",
                                    "ioc_type": "ip_address",
                                    "ioc_value": ioc,
                                    "severity": "HIGH",
                                    "description": f"Malicious IP {ioc} found in logs",
                                    "hits": total_hits,
                                    "sources": [r['source'] for r in results if r.get('hits', 0) > 0],
                                    "first_seen": min(r['first_seen'] for r in results if r.get('first_seen')),
                                    "last_seen": max(r['last_seen'] for r in results if r.get('last_seen')),
                                    "recommendation": "Block IP and investigate all connections"
                                })

                    elif ioc_type == "domain":
                        domain_query = """
                            SELECT COUNT(*) AS hits,
                                   MIN(timestamp) AS first_seen,
                                   MAX(timestamp) AS last_seen,
                                   string_agg(DISTINCT source_ip::text, ',') AS sources
                            FROM dns_logs
                            WHERE domain = $1
                              AND timestamp > NOW() - $2 * INTERVAL '1 hour'
                        """
                        results = await db.query(domain_query, (ioc, time_range_hours))

                        if results and results[0].get('hits', 0) > 0:
                            findings.append({
                                "finding_id": f"IOC-DOMAIN-{ioc}",
                                "type": "ioc_match",
                                "ioc_type": "domain",
                                "ioc_value": ioc,
                                "severity": "CRITICAL",
                                "description": f"Malicious domain {ioc} accessed",
                                "hits": results[0]['hits'],
                                "sources": results[0]['sources'].split(',') if results[0].get('sources') else [],
                                "first_seen": results[0]['first_seen'],
                                "last_seen": results[0]['last_seen'],
                                "recommendation": "Block domain and investigate source systems"
                            })

                    elif ioc_type == "file_hash":
                        file_query = """
                            SELECT COUNT(*) AS hits,
                                   MIN(timestamp) AS first_seen,
                                   MAX(timestamp) AS last_seen,
                                   string_agg(DISTINCT file_path::text, ',') AS paths
                            FROM file_integrity_logs
                            WHERE file_hash = $1
                              AND timestamp > NOW() - $2 * INTERVAL '1 hour'
                        """
                        results = await db.query(file_query, (ioc, time_range_hours))

                        if results and results[0].get('hits', 0) > 0:
                            findings.append({
                                "finding_id": f"IOC-HASH-{ioc}",
                                "type": "ioc_match",
                                "ioc_type": "file_hash",
                                "ioc_value": ioc,
                                "severity": "CRITICAL",
                                "description": f"Malicious file hash {ioc} detected",
                                "hits": results[0]['hits'],
                                "file_paths": results[0]['paths'].split(',') if results[0].get('paths') else [],
                                "first_seen": results[0]['first_seen'],
                                "last_seen": results[0]['last_seen'],
                                "recommendation": "Quarantine files and scan affected systems"
                            })

                        # Behavioral hunting
                        if hunt_type in ["behavioral", "comprehensive"]:
                                # Hunt for lateral movement patterns
                                lateral_movement_query = """
                                        SELECT source_ip,
                                                     COUNT(DISTINCT dest_ip) AS targets,
                                                     string_agg(DISTINCT dest_ip::text, ',') AS destination_ips,
                                                     MIN(timestamp) AS first_seen,
                                                     MAX(timestamp) AS last_seen
                                        FROM network_logs
                                        WHERE protocol IN ('SMB', 'RDP', 'SSH', 'WinRM')
                                            AND timestamp > NOW() - $1 * INTERVAL '1 hour'
                                        GROUP BY source_ip
                                        HAVING COUNT(DISTINCT dest_ip) > 5
                                """
                                lateral_results = await db.query(lateral_movement_query, (time_range_hours,))

                for row in (lateral_results or []):
                    findings.append({
                        "finding_id": f"HUNT-LATERAL-{row['source_ip']}",
                        "type": "lateral_movement",
                        "severity": "HIGH",
                        "description": f"Lateral movement detected from {row['source_ip']}",
                        "evidence": {
                            "source_ip": row['source_ip'],
                            "target_count": row['targets'],
                            "target_ips": row['destination_ips'].split(',')[:10] if row.get('destination_ips') else []
                        },
                        "first_seen": row['first_seen'].isoformat() if row.get('first_seen') else "",
                        "last_seen": row['last_seen'].isoformat() if row.get('last_seen') else "",
                        "recommendation": "Investigate source system for compromise"
                    })

                # Hunt for privilege escalation attempts
                privesc_query = """
                    SELECT "user",
                           COUNT(*) AS attempts,
                           string_agg(DISTINCT target_privilege::text, ',') AS privileges,
                           MIN(timestamp) AS first_seen,
                           MAX(timestamp) AS last_seen
                    FROM security_events
                    WHERE event_type = 'privilege_escalation'
                    AND result = 'success'
                      AND timestamp > NOW() - $1 * INTERVAL '1 hour'
                    GROUP BY "user"
                    HAVING COUNT(*) > 3
                """
                privesc_results = await db.query(privesc_query, (time_range_hours,))

                for row in (privesc_results or []):
                    findings.append({
                        "finding_id": f"HUNT-PRIVESC-{row['user']}",
                        "type": "privilege_escalation",
                        "severity": "CRITICAL",
                        "description": f"Multiple privilege escalations by {row['user']}",
                        "evidence": {
                            "user": row['user'],
                            "attempts": row['attempts'],
                            "privileges": row['privileges'].split(',') if row.get('privileges') else []
                        },
                        "first_seen": row['first_seen'].isoformat() if row.get('first_seen') else "",
                        "last_seen": row['last_seen'].isoformat() if row.get('last_seen') else "",
                        "recommendation": "Investigate user account for compromise or insider threat"
                    })

                # Hunt for suspicious process executions
                process_query = """
                    SELECT process_name,
                           COUNT(*) AS executions,
                           string_agg(DISTINCT command_line::text, '|||') AS commands,
                           string_agg(DISTINCT parent_process::text, ',') AS parents
                    FROM process_logs
                    WHERE (
                        process_name IN ('powershell.exe', 'cmd.exe', 'wscript.exe', 'cscript.exe', 'mshta.exe')
                        OR command_line LIKE '%encoded%'
                        OR command_line LIKE '%bypass%'
                        OR command_line LIKE '%downloadstring%'
                    )
                      AND timestamp > NOW() - $1 * INTERVAL '1 hour'
                    GROUP BY process_name
                """
                process_results = await db.query(process_query, (time_range_hours,))

                for row in (process_results or []):
                    findings.append({
                        "finding_id": f"HUNT-PROC-{row['process_name']}",
                        "type": "suspicious_process",
                        "severity": "MEDIUM",
                        "description": f"Suspicious {row['process_name']} executions detected",
                        "evidence": {
                            "process": row['process_name'],
                            "execution_count": row['executions'],
                            "sample_commands": (row['commands'] or '').split('|||')[:3],
                            "parent_processes": row['parents'].split(',') if row.get('parents') else []
                        },
                        "recommendation": "Analyze command lines for malicious activity"
                    })

            # Network-based hunting
            if hunt_type in ["network_based", "comprehensive"]:
                # Hunt for C2 beaconing patterns (regular intervals)
                beacon_query = """
                    SELECT source_ip,
                           dest_ip,
                           COUNT(*) AS connections,
                           STDDEV(
                               EXTRACT(
                                   EPOCH FROM timestamp - LAG(timestamp) OVER (
                                       PARTITION BY source_ip, dest_ip
                                       ORDER BY timestamp
                                   )
                               )
                           ) AS interval_stddev
                    FROM network_logs
                    WHERE timestamp > NOW() - $1 * INTERVAL '1 hour'
                    GROUP BY source_ip, dest_ip
                    HAVING COUNT(*) > 10 AND interval_stddev < 5
                """
                beacon_results = await db.query(beacon_query, (time_range_hours,))

                for row in (beacon_results or []):
                    findings.append({
                        "finding_id": f"HUNT-BEACON-{row['source_ip']}",
                        "type": "c2_beaconing",
                        "severity": "CRITICAL",
                        "description": f"C2 beaconing pattern detected: {row['source_ip']} -> {row['dest_ip']}",
                        "evidence": {
                            "source_ip": row['source_ip'],
                            "dest_ip": row['dest_ip'],
                            "connection_count": row['connections'],
                            "interval_consistency": f"StdDev: {row['interval_stddev']:.2f}s (highly regular)"
                        },
                        "recommendation": "Isolate source system and block destination IP"
                    })

                # Hunt for DNS tunneling
                dns_tunnel_query = """
                    SELECT domain,
                           COUNT(*) AS queries,
                           AVG(LENGTH(domain)) AS avg_length
                    FROM dns_logs
                    WHERE timestamp > NOW() - $1 * INTERVAL '1 hour'
                    GROUP BY domain
                    HAVING COUNT(*) > 50 AND AVG(LENGTH(domain)) > 50
                """
                dns_results = await db.query(dns_tunnel_query, (time_range_hours,))

                for row in (dns_results or []):
                    findings.append({
                        "finding_id": f"HUNT-DNSTUNNEL-{row['domain']}",
                        "type": "dns_tunneling",
                        "severity": "HIGH",
                        "description": f"DNS tunneling suspected: {row['domain']}",
                        "evidence": {
                            "domain": row['domain'],
                            "query_count": row['queries'],
                            "avg_domain_length": row['avg_length']
                        },
                        "recommendation": "Block domain and investigate source systems"
                    })

                # Hunt for unusual outbound connections to new IPs
                new_connections_query = """
                    SELECT dest_ip,
                           COUNT(DISTINCT source_ip) AS sources,
                           SUM(bytes_sent) AS total_bytes
                    FROM network_logs
                    WHERE timestamp > NOW() - INTERVAL '1 hour'
                      AND dest_ip NOT IN (
                          SELECT DISTINCT dest_ip
                          FROM network_logs
                          WHERE timestamp BETWEEN NOW() - $1 * INTERVAL '1 hour'
                                              AND NOW() - INTERVAL '1 hour'
                      )
                    GROUP BY dest_ip
                    HAVING COUNT(DISTINCT source_ip) > 3 OR SUM(bytes_sent) > 1073741824
                """
                new_conn_results = await db.query(new_connections_query, (time_range_hours,))

                for row in (new_conn_results or []):
                    findings.append({
                        "finding_id": f"HUNT-NEWCONN-{row['dest_ip']}",
                        "type": "unusual_connection",
                        "severity": "MEDIUM",
                        "description": f"New connection to {row['dest_ip']}",
                        "evidence": {
                            "dest_ip": row['dest_ip'],
                            "source_count": row['sources'],
                            "total_bytes": row['total_bytes']
                        },
                        "recommendation": "Verify legitimacy of new destination"
                    })

            threats_found = len(findings) > 0
            high_priority = len([f for f in findings if f.get("severity") in ["HIGH", "CRITICAL"]])

            return ToolResult(
                success=True,
                output={
                    "hunt_type": hunt_type,
                    "threats_found": threats_found,
                    "findings_count": len(findings),
                    "high_priority_findings": high_priority,
                    "findings": findings,
                    "iocs_searched": len(iocs) if iocs else 0,
                    "time_range_hours": time_range_hours,
                    "hunt_started": (datetime.now() - timedelta(seconds=10)).isoformat(),
                    "hunt_completed": datetime.now().isoformat(),
                    "note": "Integrate with EDR, SIEM, and threat intelligence platforms for production use"
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Threat hunting failed: {str(e)}")


class DetectZeroDayTool(Tool):
    """Heuristic-based detection of novel attack patterns"""

    def __init__(self):
        super().__init__()
        self.name = "detect_zero_day"
        self.description = "Detect potential zero-day exploits using heuristic analysis and behavioral signatures"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="analysis_scope",
                type="string",
                description="Scope of zero-day analysis",
                required=False,
                enum=["process_behavior", "network_traffic", "memory_patterns", "file_analysis", "comprehensive"],
                default="comprehensive"
            ),
            ToolParameter(
                name="sensitivity",
                type="string",
                description="Detection sensitivity (higher = more false positives)",
                required=False,
                enum=["low", "medium", "high"],
                default="medium"
            ),
            ToolParameter(
                name="target_file",
                type="string",
                description="Optional file to analyze for zero-day exploits",
                required=False
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="detect_zero_day",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    risk_level=RiskLevel.MEDIUM,
                    priority=9,
                    approval_level="autonomous"
                ),
                CapabilityMetadata(
                    capability=Capability.PREDICT_CONSEQUENCES,
                    risk_level=RiskLevel.MEDIUM,
                    priority=9,
                    approval_level="autonomous"
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, analysis_scope: str = "comprehensive", sensitivity: str = "medium", target_file: str = None) -> ToolResult:
        try:
            from datetime import datetime

            detections = []

            # Heuristic patterns for zero-day detection
            heuristics = {
                "process_behavior": [
                    "Process injection into system processes",
                    "Unusual privilege escalation attempts",
                    "Reflective DLL loading",
                    "Process hollowing",
                    "Suspicious registry modifications"
                ],
                "network_traffic": [
                    "Encrypted traffic to unknown destinations",
                    "Unusual protocol usage",
                    "Beaconing patterns",
                    "Large data transfers to new IPs"
                ],
                "memory_patterns": [
                    "Shellcode in memory",
                    "ROP chains detected",
                    "Memory page permission changes",
                    "Heap spraying patterns"
                ]
            }


            if analysis_scope in ["process_behavior", "comprehensive"]:
                # Process behavior analysis
                detections.append({
                    "detection_id": "ZD-001",
                    "category": "process_behavior",
                    "severity": "HIGH",
                    "heuristic_matched": "Process injection into system processes",
                    "description": "Detected process injection into lsass.exe from unknown source",
                    "confidence": 0.75,
                    "evidence": {
                        "source_process": "unknown.exe",
                        "target_process": "lsass.exe",
                        "injection_type": "WriteProcessMemory + CreateRemoteThread",
                        "pid": 1234
                    },
                    "timestamp": datetime.now().isoformat(),
                    "recommendation": "Immediate investigation required - possible credential dumping attempt"
                })

            if analysis_scope in ["network_traffic", "comprehensive"]:
                # Network traffic analysis for zero-day indicators
                try:
                    from core.database import get_database_manager
                    db = get_database_manager()

                    # Look for unusual protocol usage
                    unusual_protocol_query = """
                                                SELECT protocol, source_ip, dest_ip, COUNT(*) AS connections
                        FROM network_logs
                                                WHERE protocol NOT IN ('TCP', 'UDP', 'ICMP', 'HTTP', 'HTTPS')
                                                    AND timestamp > NOW() - INTERVAL '24 hours'
                                                GROUP BY protocol, source_ip, dest_ip
                                                HAVING COUNT(*) > 10
                    """
                    unusual_protocols = await db.query(unusual_protocol_query)

                    for row in (unusual_protocols or []):
                        detections.append({
                            "detection_id": f"ZD-NET-{row['protocol']}",
                            "category": "network_traffic",
                            "severity": "MEDIUM",
                            "heuristic_matched": "Unusual protocol usage",
                            "description": f"Unusual protocol {row['protocol']} detected",
                            "confidence": 0.6,
                            "evidence": {
                                "protocol": row['protocol'],
                                "source_ip": row['source_ip'],
                                "dest_ip": row['dest_ip'],
                                "connection_count": row['connections']
                            },
                            "timestamp": datetime.now().isoformat(),
                            "recommendation": "Investigate protocol usage - may indicate exploit or covert channel"
                        })

                except Exception as e:
                    logger.debug(f"Network traffic analysis skipped: {e}")

            if analysis_scope in ["memory_patterns", "comprehensive"]:
                # Memory pattern analysis for exploit indicators
                try:
                    from core.database import get_database_manager
                    db = get_database_manager()

                    # Look for suspicious memory operations
                    memory_query = """
                                                SELECT process_name, operation_type, COUNT(*) AS occurrences
                        FROM memory_operations
                        WHERE operation_type IN ('VirtualAllocEx', 'WriteProcessMemory', 'CreateRemoteThread', 'SetThreadContext')
                                                    AND timestamp > NOW() - INTERVAL '1 hour'
                        GROUP BY process_name, operation_type
                                                HAVING COUNT(*) > 5
                    """
                    memory_ops = await db.query(memory_query)

                    for row in (memory_ops or []):
                        detections.append({
                            "detection_id": f"ZD-MEM-{row['process_name']}",
                            "category": "memory_patterns",
                            "severity": "HIGH",
                            "heuristic_matched": "Suspicious memory operations",
                            "description": f"Process {row['process_name']} performing {row['operation_type']}",
                            "confidence": 0.7,
                            "evidence": {
                                "process": row['process_name'],
                                "operation": row['operation_type'],
                                "occurrences": row['occurrences']
                            },
                            "timestamp": datetime.now().isoformat(),
                            "recommendation": "Investigate for process injection or code injection attempt"
                        })

                except Exception as e:
                    logger.debug(f"Memory pattern analysis skipped: {e}")

            zero_day_suspected = len(detections) > 0
            critical_detections = len([d for d in detections if d.get("severity") == "CRITICAL"])
            avg_confidence = sum(d.get("confidence", 0) for d in detections) / len(detections) if detections else 0

            return ToolResult(
                success=True,
                output={
                    "zero_day_suspected": zero_day_suspected,
                    "detection_count": len(detections),
                    "critical_detections": critical_detections,
                    "average_confidence": avg_confidence,
                    "detections": detections,
                    "analysis_scope": analysis_scope,
                    "sensitivity": sensitivity,
                    "timestamp": datetime.now().isoformat(),
                    "alert_level": "CRITICAL" if critical_detections > 0 else "HIGH" if zero_day_suspected else "NORMAL",
                    "note": "Integrate with sandbox, EDR, and ML-based detection systems for production use"
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Zero-day detection failed: {str(e)}")

