"""
X.509 Certificate Generation and Management.

This module provides:
- Deterministic X.509 certificate generation
- Self-signed and CA-signed certificate support
- Multiple key types (RSA 2048/4096, EC P-256/P-384/P-521)
- Certificate bundling utilities
- Comprehensive certificate configuration
"""

# Standard library imports
import sys
import json
import hashlib
import hmac
import warnings
import ipaddress
import datetime
from typing import Optional, List, Literal

# Third-party imports
import click
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.x509.oid import NameOID, ExtensionOID, ExtendedKeyUsageOID
from pydantic import BaseModel, Field, field_validator, ConfigDict

# Local imports from common module
from degen_crypto.lib_common import (
    cli,
    parse_timestamp,
    EntropyMetrics,
    SeedDerivation,
    InputLoader,
)
from degen_crypto.lib_crypto_asym import AsymmetricKeyGenerator


# ============================================================================
# X.509 Pydantic Models
# ============================================================================

class X509SubjectInfo(BaseModel):
    """X.509 certificate subject information."""

    CN: str = Field(..., description="Common Name")
    O: Optional[str] = Field(default=None, description="Organization")
    OU: Optional[str] = Field(default=None, description="Organizational Unit")
    C: Optional[str] = Field(default=None, description="Country")
    ST: Optional[str] = Field(default=None, description="State or Province")
    L: Optional[str] = Field(default=None, description="Locality/City")

class X509IssuerInfo(BaseModel):
    """X.509 certificate issuer information."""

    CN: Optional[str] = Field(default=None, description="Common Name")
    O: Optional[str] = Field(default=None, description="Organization")
    OU: Optional[str] = Field(default=None, description="Organizational Unit")
    C: Optional[str] = Field(default=None, description="Country")

class X509Metadata(BaseModel):
    """Metadata for X.509 certificate generation."""

    derivation_path: str = Field(..., description="Derivation path used")
    derivation_method: str = Field(..., description="Derivation method")
    iterations: int = Field(..., description="Number of iterations")
    key_type: str = Field(..., description="Private key type")
    is_ca: bool = Field(..., description="Whether this is a CA certificate")
    ca_signed: bool = Field(..., description="Whether this is CA-signed")
    deterministic_serial: bool = Field(..., description="Whether serial number is deterministic")
    deterministic_key: bool = Field(..., description="Whether private key is deterministic")
    seed_entropy: Optional[EntropyMetrics] = Field(default=None, description="Entropy metrics of the seed phrase")

class X509Output(BaseModel):
    """Complete X.509 certificate output."""

    model_config = ConfigDict(populate_by_name=True)

    private_key: str = Field(..., description="Private key in PEM format")
    certificate: str = Field(..., description="Certificate in PEM format")
    subject: X509SubjectInfo = Field(..., description="Certificate subject")
    issuer: Optional[X509IssuerInfo] = Field(default=None, description="Certificate issuer (for CA-signed certs)")
    serial_number: str = Field(..., description="Certificate serial number")
    validity_days: int = Field(..., description="Certificate validity in days")
    key_usage: List[str] = Field(..., description="Enabled key usage flags")
    extended_key_usage: List[str] = Field(..., description="Enabled extended key usage flags")
    san_dns: Optional[List[str]] = Field(default=None, description="DNS Subject Alternative Names")
    san_ip: Optional[List[str]] = Field(default=None, description="IP Subject Alternative Names")
    path_length: Optional[int] = Field(default=None, description="CA path length constraint")
    metadata: X509Metadata = Field(..., alias="_metadata", description="Generation metadata")


# ============================================================================
# X.509 Bundle Pydantic Models
# ============================================================================

class X509BundleMetadata(BaseModel):
    """Metadata for X.509 CA bundle."""

    bundled_from_files: bool = Field(..., description="Whether bundle was created from files")
    is_ca: bool = Field(..., description="Whether certificate is a CA")
    key_type: str = Field(..., description="Private key type")
    not_valid_before: str = Field(..., description="Certificate not-valid-before timestamp")
    not_valid_after: str = Field(..., description="Certificate not-valid-after timestamp")

class X509BundleOutput(BaseModel):
    """X.509 CA bundle output."""

    model_config = ConfigDict(populate_by_name=True)

    certificate: str = Field(..., description="CA certificate in PEM format")
    private_key: str = Field(..., description="CA private key in PEM format")
    subject: X509SubjectInfo = Field(..., description="Certificate subject")
    serial_number: str = Field(..., description="Certificate serial number")
    metadata: X509BundleMetadata = Field(..., alias="_metadata", description="Bundle metadata")


# ============================================================================
# X.509 Configuration Models
# ============================================================================

class X509KeyConfig(BaseModel):
    """Configuration for X.509 private key generation."""

    model_config = ConfigDict(frozen=True)

    key_type: Literal["rsa2048", "rsa4096", "ec256", "ec384", "ec521"] = Field(
        default="rsa2048",
        description="Private key type and size"
    )

    def get_key_params(self) -> tuple[str, int | str]:
        """
        Get key algorithm and parameters.

        Returns:
            Tuple of (algorithm, parameter) where parameter is key_size for RSA or curve_name for EC
        """
        if self.key_type == "rsa2048":
            return ("rsa", 2048)
        elif self.key_type == "rsa4096":
            return ("rsa", 4096)
        elif self.key_type == "ec256":
            return ("ec", "secp256r1")
        elif self.key_type == "ec384":
            return ("ec", "secp384r1")
        elif self.key_type == "ec521":
            return ("ec", "secp521r1")
        else:
            raise ValueError(f"Unknown key type: {self.key_type}")


class X509NameConfig(BaseModel):
    """Configuration for X.509 Distinguished Name (Subject/Issuer)."""

    common_name: str = Field(..., min_length=1, description="Common Name (CN)")
    organization: Optional[str] = Field(default=None, description="Organization (O)")
    organizational_unit: Optional[str] = Field(default=None, description="Organizational Unit (OU)")
    country: Optional[str] = Field(default=None, max_length=2, description="Country (C) - 2 letter code")
    state: Optional[str] = Field(default=None, description="State or Province (ST)")
    locality: Optional[str] = Field(default=None, description="Locality/City (L)")

    @field_validator('common_name')
    @classmethod
    def validate_common_name(cls, v: str) -> str:
        """Validate common name is not empty."""
        if not v or not v.strip():
            raise ValueError("Common name cannot be empty")
        return v.strip()

    @field_validator('country')
    @classmethod
    def validate_country(cls, v: Optional[str]) -> Optional[str]:
        """Validate country code is 2 letters."""
        if v is not None:
            v = v.strip().upper()
            if len(v) != 2:
                raise ValueError("Country code must be exactly 2 letters")
        return v


class X509BasicCertConfig(BaseModel):
    """Basic configuration for X.509 certificate generation."""

    subject: X509NameConfig = Field(..., description="Certificate subject")
    validity_days: int = Field(default=365, ge=1, le=36500, description="Certificate validity in days")
    is_ca: bool = Field(default=False, description="Whether this is a CA certificate")
    path_length: Optional[int] = Field(default=None, ge=0, description="Maximum path length for CA (None = unlimited)")

    # Subject Alternative Names
    san_dns: List[str] = Field(default_factory=list, description="DNS names for Subject Alternative Name")
    san_ip: List[str] = Field(default_factory=list, description="IP addresses for Subject Alternative Name")

    # Key Usage
    digital_signature: bool = Field(default=True, description="Key usage: digitalSignature")
    key_encipherment: bool = Field(default=False, description="Key usage: keyEncipherment")
    key_cert_sign: bool = Field(default=False, description="Key usage: keyCertSign")
    crl_sign: bool = Field(default=False, description="Key usage: cRLSign")
    key_agreement: bool = Field(default=False, description="Key usage: keyAgreement")

    # Extended Key Usage
    server_auth: bool = Field(default=False, description="Extended key usage: TLS Web Server Authentication")
    client_auth: bool = Field(default=False, description="Extended key usage: TLS Web Client Authentication")
    code_signing: bool = Field(default=False, description="Extended key usage: Code Signing")
    email_protection: bool = Field(default=False, description="Extended key usage: Email Protection")

    @field_validator('san_dns')
    @classmethod
    def validate_dns_names(cls, v: List[str]) -> List[str]:
        """Validate DNS names (basic validation)."""
        validated = []
        for name in v:
            name = name.strip().lower()
            if not name:
                continue
            # Basic validation: allow alphanumeric, hyphens, dots, and wildcards
            if not all(c.isalnum() or c in '.-*' for c in name):
                raise ValueError(f"Invalid DNS name: {name}")
            validated.append(name)
        return validated

    @field_validator('san_ip')
    @classmethod
    def validate_ip_addresses(cls, v: List[str]) -> List[str]:
        """Validate IP addresses (IPv4 and IPv6)."""
        validated = []
        for ip_str in v:
            ip_str = ip_str.strip()
            if not ip_str:
                continue
            try:
                # This will validate both IPv4 and IPv6
                ipaddress.ip_address(ip_str)
                validated.append(ip_str)
            except ValueError:
                raise ValueError(f"Invalid IP address: {ip_str}")
        return validated

    @field_validator('path_length')
    @classmethod
    def validate_path_length(cls, v: Optional[int], info) -> Optional[int]:
        """Validate path_length is only set for CA certificates."""
        # Note: in Pydantic v2, we need to check if is_ca exists in values
        # This validator runs before model construction, so we can't access self.is_ca
        # We'll validate this in the cert generation function instead
        return v

    def get_key_usage_flags(self) -> List[str]:
        """Get list of enabled key usage flags."""
        flags = []
        if self.digital_signature:
            flags.append("digitalSignature")
        if self.key_encipherment:
            flags.append("keyEncipherment")
        if self.key_cert_sign:
            flags.append("keyCertSign")
        if self.crl_sign:
            flags.append("cRLSign")
        if self.key_agreement:
            flags.append("keyAgreement")
        return flags

    def get_extended_key_usage_flags(self) -> List[str]:
        """Get list of enabled extended key usage flags."""
        flags = []
        if self.server_auth:
            flags.append("serverAuth")
        if self.client_auth:
            flags.append("clientAuth")
        if self.code_signing:
            flags.append("codeSigning")
        if self.email_protection:
            flags.append("emailProtection")
        return flags


# ============================================================================
# X.509 Certificate Management Class
# ============================================================================

class X509CertificateManager:
    """
    Class methods for X.509 certificate generation and management.

    Provides deterministic X.509 certificate generation with support for
    self-signed and CA-signed certificates, multiple key types, and
    comprehensive certificate configuration.
    """

    @classmethod
    def derive_serial_number(cls, seed_phrase: str, context: str) -> int:
        """
        Derive a deterministic serial number for X.509 certificates.

        Serial numbers must be positive integers up to 20 bytes (160 bits).
        We use HMAC-SHA256 to create a deterministic but unique serial number.

        Args:
            seed_phrase: Master seed phrase
            context: Context for derivation (e.g., 'x509/example.com/0')

        Returns:
            Positive integer serial number (deterministic)
        """
        # Use HMAC-SHA256 for deterministic serial generation
        seed = SeedDerivation.derive_master_seed(
            seed_phrase=seed_phrase,
            salt_phrase=f"{context}/serial",
            iterations=2048,
            dklen=32
        )

        # Convert first 20 bytes to integer (x509 serial max is 20 bytes)
        serial_bytes = seed[:20]
        serial_int = int.from_bytes(serial_bytes, byteorder='big')

        # Ensure it's positive (clear the sign bit if needed)
        # x509 serial numbers should be positive
        serial_int = serial_int & ((1 << 159) - 1)  # Use 159 bits (20 bytes - 1 bit for sign)

        # Ensure it's at least 1 (serial cannot be 0)
        if serial_int == 0:
            serial_int = 1

        return serial_int

    @classmethod
    def load_ca_bundle(cls, ca_input: str) -> tuple[x509.Certificate, rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey]:
        """
        Load CA certificate and private key from file or stdin.

        Expected input format (JSON):
        {
          "certificate": "-----BEGIN CERTIFICATE-----...",
          "private_key": "-----BEGIN ... PRIVATE KEY-----..."
        }

        Args:
            ca_input: File path or '-' for stdin

        Returns:
            Tuple of (CA certificate, CA private key)

        Raises:
            ValueError: If input is invalid or cannot be parsed
        """
        # Read CA bundle from supported sources
        try:
            ca_json = InputLoader.load_text(ca_input, description="CA bundle")
        except ValueError as exc:
            raise ValueError(str(exc))

        if ca_json is None:
            raise ValueError("CA bundle input is required.")

        # Parse JSON
        try:
            ca_data = json.loads(ca_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in CA bundle: {e}")

        # Extract certificate and private key PEM
        if 'certificate' not in ca_data:
            raise ValueError("CA bundle missing 'certificate' field")
        if 'private_key' not in ca_data:
            raise ValueError("CA bundle missing 'private_key' field")

        cert_pem = ca_data['certificate']
        key_pem = ca_data['private_key']

        # Load certificate
        try:
            ca_cert = x509.load_pem_x509_certificate(cert_pem.encode('utf-8'), default_backend())
        except Exception as e:
            raise ValueError(f"Failed to load CA certificate: {e}")

        # Load private key
        try:
            ca_key = serialization.load_pem_private_key(
                key_pem.encode('utf-8'),
                password=None,
                backend=default_backend()
            )
        except Exception as e:
            raise ValueError(f"Failed to load CA private key: {e}")

        # Validate that the key matches the certificate
        try:
            # Get public keys
            cert_public_key = ca_cert.public_key()
            key_public_key = ca_key.public_key()

            # Compare public key bytes
            cert_pub_bytes = cert_public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            key_pub_bytes = key_public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )

            if cert_pub_bytes != key_pub_bytes:
                raise ValueError("CA private key does not match CA certificate")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to validate CA key/cert pair: {e}")

        # Verify it's a CA certificate
        try:
            basic_constraints = ca_cert.extensions.get_extension_for_oid(
                ExtensionOID.BASIC_CONSTRAINTS
            ).value
            if not basic_constraints.ca:
                raise ValueError("Certificate is not a CA certificate (basicConstraints CA:FALSE)")
        except x509.ExtensionNotFound:
            raise ValueError("Certificate is missing basicConstraints extension")

        return ca_cert, ca_key

    @classmethod
    def build_x509_name(cls, name_config: X509NameConfig) -> x509.Name:
        """
        Build an X.509 Name object from configuration.

        Args:
            name_config: Name configuration

        Returns:
            x509.Name object
        """
        name_attributes = [
            x509.NameAttribute(NameOID.COMMON_NAME, name_config.common_name)
        ]

        if name_config.organization:
            name_attributes.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, name_config.organization))
        if name_config.organizational_unit:
            name_attributes.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, name_config.organizational_unit))
        if name_config.country:
            name_attributes.append(x509.NameAttribute(NameOID.COUNTRY_NAME, name_config.country))
        if name_config.state:
            name_attributes.append(x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, name_config.state))
        if name_config.locality:
            name_attributes.append(x509.NameAttribute(NameOID.LOCALITY_NAME, name_config.locality))

        return x509.Name(name_attributes)


    @classmethod
    def build_basic_certificate(cls,
        private_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey,
        cert_config: X509BasicCertConfig,
        serial_number: int,
        ca_cert: Optional[x509.Certificate] = None,
        ca_key: Optional[rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey] = None,
        not_valid_before: Optional[datetime.datetime] = None,
        not_valid_after: Optional[datetime.datetime] = None
    ) -> x509.Certificate:
        """
        Build an X.509 certificate (self-signed or CA-signed).

        Args:
            private_key: Subject's private key
            cert_config: Certificate configuration
            serial_number: Certificate serial number
            ca_cert: CA certificate (for CA-signed certs, None for self-signed)
            ca_key: CA private key (for CA-signed certs, None for self-signed)

        Returns:
            x509.Certificate object
        """
        # Build subject name
        subject = cls.build_x509_name(cert_config.subject)

        # Determine issuer and signing key
        if ca_cert is not None and ca_key is not None:
            # CA-signed certificate
            issuer = ca_cert.subject
            signing_key = ca_key
        else:
            # Self-signed: issuer = subject
            issuer = subject
            signing_key = private_key

        # Get public key (subject's public key)
        public_key = private_key.public_key()

        # Build certificate
        builder = x509.CertificateBuilder()
        builder = builder.subject_name(subject)
        builder = builder.issuer_name(issuer)
        builder = builder.public_key(public_key)
        builder = builder.serial_number(serial_number)

        # Set validity period
        if not_valid_before is not None:
            # Use custom timestamps
            builder = builder.not_valid_before(not_valid_before)
            if not_valid_after is not None:
                builder = builder.not_valid_after(not_valid_after)
            else:
                # If only start time is set, use validity_days from config
                builder = builder.not_valid_after(not_valid_before + datetime.timedelta(days=cert_config.validity_days))
        else:
            # Use current time and validity_days
            now = datetime.datetime.now(datetime.timezone.utc)
            builder = builder.not_valid_before(now)
            builder = builder.not_valid_after(now + datetime.timedelta(days=cert_config.validity_days))

        # Add Subject Key Identifier
        builder = builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(public_key),
            critical=False
        )

        # Add Authority Key Identifier
        if ca_cert is not None:
            # CA-signed: use CA's subject key identifier
            builder = builder.add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
                critical=False
            )
        else:
            # Self-signed: issuer key = subject key
            builder = builder.add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(public_key),
                critical=False
            )

        # Add Basic Constraints
        builder = builder.add_extension(
            x509.BasicConstraints(ca=cert_config.is_ca, path_length=cert_config.path_length),
            critical=True
        )

        # Add Key Usage
        key_usage_flags = {}
        key_usage_flags['digital_signature'] = cert_config.digital_signature
        key_usage_flags['key_encipherment'] = cert_config.key_encipherment
        key_usage_flags['key_cert_sign'] = cert_config.key_cert_sign
        key_usage_flags['crl_sign'] = cert_config.crl_sign
        key_usage_flags['key_agreement'] = cert_config.key_agreement

        # Add other key usage flags as False (content_commitment, data_encipherment, encipher_only, decipher_only)
        key_usage_flags['content_commitment'] = False
        key_usage_flags['data_encipherment'] = False
        key_usage_flags['encipher_only'] = False
        key_usage_flags['decipher_only'] = False

        builder = builder.add_extension(
            x509.KeyUsage(**key_usage_flags),
            critical=True
        )

        # Add Extended Key Usage (if any flags are set)
        eku_oids = []
        if cert_config.server_auth:
            eku_oids.append(ExtendedKeyUsageOID.SERVER_AUTH)
        if cert_config.client_auth:
            eku_oids.append(ExtendedKeyUsageOID.CLIENT_AUTH)
        if cert_config.code_signing:
            eku_oids.append(ExtendedKeyUsageOID.CODE_SIGNING)
        if cert_config.email_protection:
            eku_oids.append(ExtendedKeyUsageOID.EMAIL_PROTECTION)

        if eku_oids:
            builder = builder.add_extension(
                x509.ExtendedKeyUsage(eku_oids),
                critical=False
            )

        # Add Subject Alternative Names (if any)
        san_entries = []
        for dns_name in cert_config.san_dns:
            san_entries.append(x509.DNSName(dns_name))
        for ip_str in cert_config.san_ip:
            ip_addr = ipaddress.ip_address(ip_str)
            san_entries.append(x509.IPAddress(ip_addr))

        if san_entries:
            builder = builder.add_extension(
                x509.SubjectAlternativeName(san_entries),
                critical=False
            )

        # Sign the certificate
        # Choose hash algorithm based on signing key type
        if isinstance(signing_key, rsa.RSAPrivateKey):
            hash_algorithm = hashes.SHA256()
        elif isinstance(signing_key, ec.EllipticCurvePrivateKey):
            hash_algorithm = hashes.SHA256()
        else:
            hash_algorithm = hashes.SHA256()

        certificate = builder.sign(signing_key, hash_algorithm, default_backend())

        return certificate


# ============================================================================
# Command: X.509 Certificates
# ============================================================================

@cli.command(name='derive-x509')
@click.option(
    '--hostname', '-h',
    required=True,
    help='Hostname/CN for the certificate'
)
@click.option(
    '--seed', '-s',
    required=True,
    help='Seed phrase for deterministic key and certificate derivation (supports -, @file, fd:<N>, env:<NAME>)'
)
@click.option(
    '--index', '-i',
    default=0,
    type=int,
    help='Certificate index (for multiple certs per hostname)',
    show_default=True
)
@click.option(
    '--key-type', '-k',
    type=click.Choice(['rsa2048', 'rsa4096', 'ec256', 'ec384', 'ec521']),
    default='rsa2048',
    help='Private key type and size',
    show_default=True
)
@click.option(
    '--organization', '-o',
    default=None,
    help='Organization (O) field'
)
@click.option(
    '--organizational-unit', '-ou',
    default=None,
    help='Organizational Unit (OU) field'
)
@click.option(
    '--country', '-c',
    default=None,
    help='Country (C) field - 2 letter code'
)
@click.option(
    '--state',
    default=None,
    help='State or Province (ST) field'
)
@click.option(
    '--locality',
    default=None,
    help='Locality/City (L) field'
)
@click.option(
    '--validity-days', '-v',
    default=365,
    type=int,
    help='Certificate validity in days (ignored if --not-valid-before is set)',
    show_default=True
)
@click.option(
    '--not-valid-before',
    default=None,
    help='Certificate not-valid-before timestamp (ISO8601 or Unix epoch seconds)'
)
@click.option(
    '--not-valid-after',
    default=None,
    help='Certificate not-valid-after timestamp (ISO8601 or Unix epoch seconds)'
)
@click.option(
    '--is-ca',
    is_flag=True,
    help='Generate CA certificate (sets basicConstraints CA:TRUE)'
)
@click.option(
    '--path-length',
    default=None,
    type=int,
    help='CA path length constraint (only for CA certificates)'
)
@click.option(
    '--san-dns',
    multiple=True,
    help='DNS Subject Alternative Name (can be specified multiple times)'
)
@click.option(
    '--san-ip',
    multiple=True,
    help='IP Address Subject Alternative Name (can be specified multiple times)'
)
@click.option(
    '--server-auth',
    is_flag=True,
    help='Enable TLS Web Server Authentication (extendedKeyUsage)'
)
@click.option(
    '--client-auth',
    is_flag=True,
    help='Enable TLS Web Client Authentication (extendedKeyUsage)'
)
@click.option(
    '--code-signing',
    is_flag=True,
    help='Enable Code Signing (extendedKeyUsage)'
)
@click.option(
    '--email-protection',
    is_flag=True,
    help='Enable Email Protection (extendedKeyUsage)'
)
@click.option(
    '--key-encipherment',
    is_flag=True,
    help='Enable keyEncipherment (keyUsage)'
)
@click.option(
    '--sign-with',
    default=None,
    help='Sign with CA JSON bundle (supports -, @file, fd:<N>, env:<NAME>)'
)
@click.option(
    '--pretty', '-p',
    is_flag=True,
    help='Pretty-print JSON output'
)
def derive_x509(
    hostname, seed, index, key_type, organization, organizational_unit,
    country, state, locality, validity_days, not_valid_before, not_valid_after,
    is_ca, path_length, san_dns, san_ip, server_auth, client_auth, code_signing,
    email_protection, key_encipherment, sign_with, pretty
):
    """
    Generate deterministic X.509 keys and certificates.

    This command generates self-signed or CA-signed certificates with
    deterministic private keys and serial numbers. The same seed + hostname
    + index will always produce the same certificate.

    \b
    Examples:

      \b
      # Basic server certificate with DNS SANs
      crypto-tools derive-x509 -h example.com -s "myseed" \\
        --san-dns example.com --san-dns www.example.com \\
        --server-auth --key-encipherment

      \b
      # Client authentication certificate
      crypto-tools derive-x509 -h client1 -s "myseed" \\
        --client-auth -o "My Organization"

      \b
      # CA certificate with EC key
      crypto-tools derive-x509 -h "My Root CA" -s "myseed" \\
        --is-ca --key-type ec384 -o "My Org" -c US

      \b
      # Server cert with IP SAN
      crypto-tools derive-x509 -h server1.local -s "myseed" \\
        --san-dns server1.local --san-ip 192.168.1.10 \\
        --server-auth --key-encipherment

      \b
      # CA-signed certificate (from file)
      crypto-tools derive-x509 -h "My Root CA" -s "myseed" --is-ca > ca.json
      crypto-tools derive-x509 -h server.example.com -s "myseed" \\
        --server-auth --sign-with ca.json

      \b
      # CA-signed certificate (from stdin)
      crypto-tools derive-x509 -h "My Root CA" -s "myseed" --is-ca | \\
        crypto-tools derive-x509 -h server.example.com -s "myseed" \\
          --server-auth --sign-with -

      \b
      # Extract only the certificate
      crypto-tools derive-x509 -h example.com -s "myseed" --server-auth | jq -r '.certificate'

      \b
      # Extract only the private key
      crypto-tools derive-x509 -h example.com -s "myseed" --server-auth | jq -r '.private_key'

      \b
      # Multiple certificates for same hostname (different indices)
      crypto-tools derive-x509 -h example.com -s "myseed" -i 0 --server-auth
      crypto-tools derive-x509 -h example.com -s "myseed" -i 1 --server-auth
    """
    # Load CA certificate if signing with CA
    ca_cert = None
    ca_key = None
    if sign_with:
        try:
            ca_cert, ca_key = X509CertificateManager.load_ca_bundle(sign_with)
        except ValueError as e:
            click.echo(f"Error loading CA bundle: {e}", err=True)
            sys.exit(1)

    # Parse custom timestamps if provided
    parsed_not_valid_before = None
    parsed_not_valid_after = None
    if not_valid_before:
        try:
            parsed_not_valid_before = parse_timestamp(not_valid_before)
        except ValueError as e:
            click.echo(f"Error parsing --not-valid-before: {e}", err=True)
            sys.exit(1)
    if not_valid_after:
        try:
            parsed_not_valid_after = parse_timestamp(not_valid_after)
        except ValueError as e:
            click.echo(f"Error parsing --not-valid-after: {e}", err=True)
            sys.exit(1)

    # If not-valid-before is set but not-valid-after is not, calculate from validity_days
    if parsed_not_valid_before is not None and parsed_not_valid_after is None:
        parsed_not_valid_after = parsed_not_valid_before + datetime.timedelta(days=validity_days)

    # Create derivation context
    context = f"x509/{hostname}/{index}"

    # Derive seed for key generation
    try:
        seed = InputLoader.load_text(seed, description="seed phrase", strip=True)
    except ValueError as e:
        click.echo(f"Error loading seed phrase: {e}", err=True)
        sys.exit(1)

    derived_seed, entropy_metrics = SeedDerivation.derive_entropy_seed(
        seed_phrase=seed,
        salt_phrase=context,
        dklen=64
    )

    # Derive serial number
    serial_number = X509CertificateManager.derive_serial_number(seed, context)

    # Build key configuration
    key_config = X509KeyConfig(key_type=key_type)
    key_algo, key_param = key_config.get_key_params()

    # Generate private key
    private_key = AsymmetricKeyGenerator.generate_private_key(derived_seed, key_algo, key_param)

    # Build certificate subject
    subject_config = X509NameConfig(
        common_name=hostname,
        organization=organization,
        organizational_unit=organizational_unit,
        country=country,
        state=state,
        locality=locality
    )

    # Set key usage flags based on certificate type
    # Default is digitalSignature=True (already in BasicCertConfig)
    # For CA: enable keyCertSign and cRLSign
    key_cert_sign = is_ca
    crl_sign = is_ca

    # Build certificate configuration
    cert_config = X509BasicCertConfig(
        subject=subject_config,
        validity_days=validity_days,
        is_ca=is_ca,
        path_length=path_length,
        san_dns=list(san_dns),
        san_ip=list(san_ip),
        digital_signature=True,  # Always enabled
        key_encipherment=key_encipherment or server_auth,  # Enable for server auth
        key_cert_sign=key_cert_sign,
        crl_sign=crl_sign,
        server_auth=server_auth,
        client_auth=client_auth,
        code_signing=code_signing,
        email_protection=email_protection
    )

    # Build certificate (self-signed or CA-signed)
    certificate = X509CertificateManager.build_basic_certificate(
        private_key, cert_config, serial_number, ca_cert, ca_key,
        parsed_not_valid_before, parsed_not_valid_after
    )

    # Serialize private key to PEM
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    # Serialize certificate to PEM
    certificate_pem = certificate.public_bytes(
        encoding=serialization.Encoding.PEM
    ).decode('utf-8')

    # Build subject info
    subject_info = X509SubjectInfo(CN=hostname)
    if organization:
        subject_info.O = organization
    if organizational_unit:
        subject_info.OU = organizational_unit
    if country:
        subject_info.C = country
    if state:
        subject_info.ST = state
    if locality:
        subject_info.L = locality

    # Build issuer info if CA-signed
    issuer_info = None
    if ca_cert is not None:
        issuer_subject = ca_cert.subject
        issuer_info = X509IssuerInfo()

        cn_attrs = issuer_subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if cn_attrs:
            issuer_info.CN = cn_attrs[0].value

        org_attrs = issuer_subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
        if org_attrs:
            issuer_info.O = org_attrs[0].value

        ou_attrs = issuer_subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)
        if ou_attrs:
            issuer_info.OU = ou_attrs[0].value

        country_attrs = issuer_subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)
        if country_attrs:
            issuer_info.C = country_attrs[0].value

    # Build metadata
    metadata = X509Metadata(
        derivation_path=context,
        derivation_method="PBKDF2-HMAC-SHA512",
        iterations=2048,
        key_type=key_type,
        is_ca=is_ca,
        ca_signed=ca_cert is not None,
        deterministic_serial=True,
        deterministic_key=True,  # Both RSA and EC keys are now deterministic
        seed_entropy=EntropyMetrics(**entropy_metrics) if entropy_metrics else None
    )

    # Create X509Output model
    x509_output = X509Output(
        private_key=private_key_pem,
        certificate=certificate_pem,
        subject=subject_info,
        issuer=issuer_info,
        serial_number=str(serial_number),
        validity_days=validity_days,
        key_usage=cert_config.get_key_usage_flags(),
        extended_key_usage=cert_config.get_extended_key_usage_flags(),
        san_dns=list(san_dns) if san_dns else None,
        san_ip=list(san_ip) if san_ip else None,
        path_length=path_length if is_ca and path_length is not None else None,
        _metadata=metadata
    )

    output = x509_output.model_dump(by_alias=True)

    # Output JSON
    if pretty:
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(json.dumps(output))


# ============================================================================
# Command: x509 Certificates: Bundle CA
# ============================================================================

@cli.command(name='bundle-ca')
@click.option(
    '--cert', '-c',
    required=True,
    help='CA certificate file (PEM format) or "-" for stdin'
)
@click.option(
    '--key', '-k',
    required=True,
    help='CA private key file (PEM format) or "-" for stdin'
)
@click.option(
    '--pretty', '-p',
    is_flag=True,
    help='Pretty-print JSON output'
)
def bundle_ca(cert, key, pretty):
    """
    Bundle CA certificate and private key into JSON format.

    Converts separate PEM-encoded certificate and private key files into
    the JSON format required by the --sign-with option. This is useful for
    working with existing CA certificates.

    The output JSON can be used with derive-x509 --sign-with to sign certificates.

    \b
    Examples:

      \b
      # Bundle CA from files
      crypto-tools bundle-ca --cert ca-cert.pem --key ca-key.pem > ca.json

      \b
      # Bundle and immediately use to sign
      crypto-tools bundle-ca -c ca-cert.pem -k ca-key.pem | \\
        crypto-tools derive-x509 -h server.com -s "seed" --server-auth --sign-with -

      \b
      # Read certificate from stdin, key from file
      cat ca-cert.pem | crypto-tools bundle-ca -c - -k ca-key.pem

      \b
      # Validate an existing CA bundle
      crypto-tools bundle-ca -c ca.pem -k ca-key.pem -p
    """
    # Read certificate
    if cert == '-':
        if key == '-':
            click.echo("Error: Cannot read both --cert and --key from stdin", err=True)
            sys.exit(1)
        cert_pem = sys.stdin.read()
    else:
        try:
            with open(cert, 'r') as f:
                cert_pem = f.read()
        except FileNotFoundError:
            click.echo(f"Error: Certificate file not found: {cert}", err=True)
            sys.exit(1)
        except IOError as e:
            click.echo(f"Error reading certificate file: {e}", err=True)
            sys.exit(1)

    # Read private key
    if key == '-':
        key_pem = sys.stdin.read()
    else:
        try:
            with open(key, 'r') as f:
                key_pem = f.read()
        except FileNotFoundError:
            click.echo(f"Error: Private key file not found: {key}", err=True)
            sys.exit(1)
        except IOError as e:
            click.echo(f"Error reading private key file: {e}", err=True)
            sys.exit(1)

    # Validate certificate
    try:
        ca_cert = x509.load_pem_x509_certificate(cert_pem.encode('utf-8'), default_backend())
    except Exception as e:
        click.echo(f"Error: Invalid certificate PEM format: {e}", err=True)
        sys.exit(1)

    # Validate private key
    try:
        ca_key = serialization.load_pem_private_key(
            key_pem.encode('utf-8'),
            password=None,
            backend=default_backend()
        )
    except Exception as e:
        click.echo(f"Error: Invalid private key PEM format: {e}", err=True)
        sys.exit(1)

    # Validate that the key matches the certificate
    try:
        cert_public_key = ca_cert.public_key()
        key_public_key = ca_key.public_key()

        cert_pub_bytes = cert_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        key_pub_bytes = key_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        if cert_pub_bytes != key_pub_bytes:
            click.echo("Error: Private key does not match certificate", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error validating key/cert pair: {e}", err=True)
        sys.exit(1)

    # Check if it's a CA certificate
    is_ca = False
    try:
        basic_constraints = ca_cert.extensions.get_extension_for_oid(
            ExtensionOID.BASIC_CONSTRAINTS
        ).value
        is_ca = basic_constraints.ca
    except x509.ExtensionNotFound:
        pass  # Not a CA cert, but we'll still bundle it

    if not is_ca:
        click.echo("Warning: Certificate is not a CA certificate (basicConstraints CA:FALSE or missing)", err=True)
        click.echo("Warning: This bundle can still be created but may not work with --sign-with", err=True)

    # Extract certificate information for subject
    subject = ca_cert.subject
    subject_info = X509SubjectInfo(CN="")  # Will be set below

    cn_attrs = subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if cn_attrs:
        subject_info.CN = cn_attrs[0].value

    org_attrs = subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
    if org_attrs:
        subject_info.O = org_attrs[0].value

    ou_attrs = subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)
    if ou_attrs:
        subject_info.OU = ou_attrs[0].value

    country_attrs = subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)
    if country_attrs:
        subject_info.C = country_attrs[0].value

    # Determine key type
    if isinstance(ca_key, rsa.RSAPrivateKey):
        key_type = f"rsa{ca_key.key_size}"
    elif isinstance(ca_key, ec.EllipticCurvePrivateKey):
        curve_name = ca_key.curve.name
        if curve_name == "secp256r1":
            key_type = "ec256"
        elif curve_name == "secp384r1":
            key_type = "ec384"
        elif curve_name == "secp521r1":
            key_type = "ec521"
        else:
            key_type = f"ec_{curve_name}"
    else:
        key_type = "unknown"

    # Build metadata
    metadata = X509BundleMetadata(
        bundled_from_files=True,
        is_ca=is_ca,
        key_type=key_type,
        not_valid_before=ca_cert.not_valid_before_utc.isoformat() if hasattr(ca_cert, 'not_valid_before_utc') else ca_cert.not_valid_before.isoformat(),
        not_valid_after=ca_cert.not_valid_after_utc.isoformat() if hasattr(ca_cert, 'not_valid_after_utc') else ca_cert.not_valid_after.isoformat()
    )

    # Create X509BundleOutput model
    bundle_output = X509BundleOutput(
        certificate=cert_pem,
        private_key=key_pem,
        subject=subject_info,
        serial_number=str(ca_cert.serial_number),
        _metadata=metadata
    )

    output = bundle_output.model_dump(by_alias=True)

    # Output JSON
    if pretty:
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(json.dumps(output))
