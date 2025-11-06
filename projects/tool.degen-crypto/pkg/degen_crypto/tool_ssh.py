"""
SSH Key and Certificate Generation Utilities

Provides deterministic SSH key generation using BIP85-inspired derivation
and SSH certificate generation with CA signing support.

Features:
- Deterministic Ed25519 key generation (recommended)
- RSA, ECDSA, and DSA key generation (deterministic or random)
- SHA256 fingerprints for all generated keys
- SSH certificate generation (user and host certificates)
- SSH CA bundle management
- Comprehensive certificate configuration (principals, validity, extensions)

Commands:
- derive-ssh-key: Generate SSH keypairs using BIP85-inspired derivation
- bundle-ssh-ca: Bundle SSH CA private and public keys into JSON format
- derive-ssh-cert: Generate SSH certificates with deterministic keys and CA signing
"""

# Standard library imports
import sys
import json
import secrets
import time
import ipaddress
import base64
import hashlib
from typing import (
    Dict,
    Optional,
    List,
    Literal,
)

# Third-party imports
import click
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, ec, dsa
from cryptography.hazmat.primitives.serialization import (
    SSHCertificateType,
    SSHCertificateBuilder,
)
from pydantic import (
    BaseModel,
    Field,
    field_validator,
    ConfigDict,
)

# Local imports
from degen_crypto.lib_common import cli, parse_timestamp, EntropyMetrics, SeedDerivation, InputLoader
from degen_crypto.lib_crypto_asym import AsymmetricKeyGenerator

# ============================================================================
# SSH Pydantic Models
# ============================================================================

class SSHKeyInfo(BaseModel):
    """Information about a single SSH key type."""

    private_key: str = Field(..., description="Private key in PEM/OpenSSH format")
    public_key: str = Field(..., description="Public key in OpenSSH format")
    fingerprint_sha256: str = Field(..., description="SHA256 fingerprint (same format as ssh-keygen -E sha256)")
    algorithm: str = Field(..., description="Key algorithm")
    use_case: str = Field(..., description="Recommended use case")
    key_size: str = Field(..., description="Key size information")
    deterministic: bool = Field(..., description="Whether the key is deterministic")
    filename: str = Field(..., description="Suggested filename")

class SSHKeyMetadata(BaseModel):
    """Metadata for SSH key generation."""

    derivation_path: str = Field(..., description="Derivation path used")
    derivation_method: str = Field(..., description="Derivation method")
    iterations: int = Field(..., description="Number of iterations")
    note: Optional[str] = Field(default=None, description="Additional notes")
    recommended: Optional[str] = Field(default=None, description="Recommended key type")
    all_types: Optional[List[str]] = Field(default=None, description="All available key types")
    seed_entropy: Optional[EntropyMetrics] = Field(default=None, description="Entropy metrics of the seed phrase")

class SSHKeyOutput(BaseModel):
    """Complete SSH key output with all key types and metadata."""

    model_config = ConfigDict(populate_by_name=True, exclude_none=True)

    hostname: str = Field(..., description="Target hostname")
    index: int = Field(..., description="Key index")
    keys: Dict[str, SSHKeyInfo] = Field(..., description="Dictionary of key types and their information")
    metadata: SSHKeyMetadata = Field(..., alias="_metadata", description="Generation metadata")

# ============================================================================
# SSH Bundle Pydantic Models
# ============================================================================

class SSHBundleMetadata(BaseModel):
    """Metadata for SSH CA bundle."""

    bundled_from_files: bool = Field(..., description="Whether bundle was created from files")
    key_type: str = Field(..., description="SSH key type")
    public_key_generated: bool = Field(..., description="Whether public key was generated from private key")

class SSHBundleOutput(BaseModel):
    """SSH CA bundle output."""

    model_config = ConfigDict(populate_by_name=True)

    private_key: str = Field(..., description="SSH CA private key in PEM/OpenSSH format")
    public_key: str = Field(..., description="SSH CA public key in OpenSSH format")
    metadata: SSHBundleMetadata = Field(..., alias="_metadata", description="Bundle metadata")

# ============================================================================
# SSH Certificate Pydantic Models
# ============================================================================

class SSHCertMetadata(BaseModel):
    """Metadata for SSH certificate generation."""

    derivation_path: str = Field(..., description="Derivation path used")
    derivation_method: str = Field(..., description="Derivation method")
    iterations: int = Field(..., description="Number of iterations")
    key_type: str = Field(..., description="Private key type")
    cert_type: str = Field(..., description="Certificate type (user or host)")
    ca_signed: bool = Field(..., description="Whether this is CA-signed")
    deterministic_serial: bool = Field(..., description="Whether serial number is deterministic")
    deterministic_key: bool = Field(..., description="Whether private key is deterministic")
    seed_entropy: Optional[EntropyMetrics] = Field(default=None, description="Entropy metrics of the seed phrase")

class SSHCertOutput(BaseModel):
    """SSH certificate output."""

    model_config = ConfigDict(populate_by_name=True)

    private_key: str = Field(..., description="Private key in PEM format")
    certificate: str = Field(..., description="SSH certificate in OpenSSH format")
    public_key: str = Field(..., description="Public key in OpenSSH format")
    ca_public_key: str = Field(..., description="CA public key in OpenSSH format")
    cert_type: str = Field(..., description="Certificate type (user or host)")
    key_id: str = Field(..., description="Certificate key identifier")
    principals: List[str] = Field(..., description="Valid principals")
    valid_from: int = Field(..., description="Valid-from timestamp (Unix epoch seconds)")
    valid_to: int = Field(..., description="Valid-to timestamp (Unix epoch seconds)")
    serial_number: int = Field(..., description="Certificate serial number")
    source_address: Optional[str] = Field(default=None, description="Source address restriction")
    force_command: Optional[str] = Field(default=None, description="Force command")
    metadata: SSHCertMetadata = Field(..., alias="_metadata", description="Generation metadata")

# ============================================================================
# SSH Certificate Configuration Model
# ============================================================================

class SSHCertConfig(BaseModel):
    """Configuration for SSH certificate generation."""

    cert_type: Literal["user", "host"] = Field(..., description="Certificate type (user or host)")
    key_id: str = Field(..., min_length=1, description="Certificate key identifier")
    principals: List[str] = Field(..., min_length=1, description="Valid principals (usernames or hostnames)")
    valid_from: int = Field(..., description="Valid-from timestamp (Unix epoch seconds)")
    valid_to: int = Field(..., description="Valid-to timestamp (Unix epoch seconds)")
    serial: Optional[int] = Field(default=None, ge=0, description="Optional serial number (0 to 2^64-1)")
    source_address: Optional[str] = Field(default=None, description="Source address restriction (CIDR format, user certs only)")
    force_command: Optional[str] = Field(default=None, description="Force command (user certs only)")
    extensions: Dict[str, str] = Field(default_factory=dict, description="SSH certificate extensions")

    @field_validator('principals')
    @classmethod
    def validate_principals(cls, v: List[str]) -> List[str]:
        """Validate principals are not empty."""
        validated = []
        for principal in v:
            principal = principal.strip()
            if not principal:
                continue
            validated.append(principal)
        if not validated:
            raise ValueError("At least one principal must be specified")
        return validated

    @field_validator('valid_from', 'valid_to')
    @classmethod
    def validate_timestamp(cls, v: int) -> int:
        """Validate timestamp is non-negative."""
        if v < 0:
            raise ValueError("Timestamp must be non-negative")
        return v

    @field_validator('source_address')
    @classmethod
    def validate_source_address(cls, v: Optional[str]) -> Optional[str]:
        """Validate source address is valid CIDR."""
        if v is not None:
            try:
                ipaddress.ip_network(v)
            except ValueError:
                raise ValueError(f"Invalid CIDR notation: {v}")
        return v

# ============================================================================
# SSH Key Utilities
# ============================================================================

def calculate_ssh_fingerprint_sha256(public_key_openssh: str) -> str:
    """
    Calculate SHA256 fingerprint of an SSH public key.

    Returns fingerprint in the same format as 'ssh-keygen -lf FILE -E sha256':
    SHA256:base64-encoded-hash (no padding)

    Args:
        public_key_openssh: Public key in OpenSSH format (e.g., "ssh-ed25519 AAAA...")

    Returns:
        Fingerprint string like "SHA256:abcd1234..."
    """
    # Extract the base64-encoded key data (second field)
    parts = public_key_openssh.strip().split()
    if len(parts) < 2:
        raise ValueError("Invalid OpenSSH public key format")

    # Decode the base64 key data
    key_data = base64.b64decode(parts[1])

    # Calculate SHA256 hash
    sha256_hash = hashlib.sha256(key_data).digest()

    # Encode to base64 without padding
    fingerprint_b64 = base64.b64encode(sha256_hash).decode('ascii').rstrip('=')

    return f"SHA256:{fingerprint_b64}"

# ============================================================================
# SSH Key Manager
# ============================================================================

class SSHKeyManager:
    """
    Class methods for SSH key generation and management.

    Provides deterministic SSH key generation using BIP85-inspired derivation
    and supports multiple key types (Ed25519, RSA, ECDSA).
    """

    @classmethod
    def derive_ssh_seed(cls, seed_phrase: str, hostname: str, index: int) -> tuple[bytes, Dict]:
        """
        Derive a deterministic seed for SSH key generation with entropy metrics.

        Uses BIP39-inspired PBKDF2 key derivation:
        - Combines seed phrase, hostname, and index
        - Uses PBKDF2-HMAC-SHA512 for strong key derivation
        - Produces 32 bytes of entropy for key generation
        - Returns entropy metrics about the input seed phrase

        Args:
            seed_phrase: Master seed phrase
            hostname: Target hostname for the key
            index: Index number for multiple keys per host

        Returns:
            Tuple of (32 bytes of deterministic entropy, entropy_metrics dict)
        """
        # Create hierarchical derivation context: ssh/hostname/index
        context = f"ssh/{hostname}/{index}"

        # Use unified PBKDF2 derivation with entropy measurement
        seed, entropy_metrics = SeedDerivation.derive_entropy_seed(
            seed_phrase=seed_phrase,
            salt_phrase=context,
            dklen=32
        )

        return seed, entropy_metrics

    @classmethod
    def serialize_keypair(
        cls,
        private_key: ed25519.Ed25519PrivateKey | rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | dsa.DSAPrivateKey
    ) -> tuple[str, str, str]:
        """
        Serialize a private key to SSH private/public strings with fingerprint.

        Args:
            private_key: Private key object (Ed25519, RSA, EC, or DSA)

        Returns:
            Tuple of (private_key_pem, public_key_openssh, fingerprint_sha256)
        """
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode("utf-8")

        public_openssh = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH
        ).decode("utf-8")

        fingerprint = calculate_ssh_fingerprint_sha256(public_openssh)

        return private_pem, public_openssh, fingerprint

    @classmethod
    def generate_all_ssh_keys(
        cls,
        seed_phrase: bytes | str | None,
        hostname: str,
        index: int,
        types: List[str] = None
    ) -> Dict[str, SSHKeyInfo]:
        """
        Generate specified SSH key types.

        Args:
            seed_phrase: Optional seed phrase for deterministic derivation
            hostname: Target hostname
            index: Key index
            types: List of key types to generate. Defaults to ["ed25519", "rsa", "ecdsa", "dsa"]

        Returns:
            Dict with specified key types as SSHKeyInfo models
        """
        if types is None:
            types = ["ed25519", "rsa", "ecdsa", "dsa"]

        result = {}
        context_base = f"ssh/{hostname}/{index}"
        deterministic = seed_phrase is not None

        if "ed25519" in types:
            ed25519_private_key = AsymmetricKeyGenerator.generate_ed25519_key(
                seed_phrase,
                context=f"{context_base}/ed25519"
            )
            ed25519_priv, ed25519_pub, ed25519_fp = cls.serialize_keypair(ed25519_private_key)
            result["ed25519"] = SSHKeyInfo(
                private_key=ed25519_priv,
                public_key=f"{ed25519_pub.strip()} {hostname}@{index}-ed25519",
                fingerprint_sha256=ed25519_fp,
                algorithm="Ed25519",
                use_case="Modern SSH - recommended for clients and hosts",
                key_size="256-bit (fixed)",
                deterministic=deterministic,
                filename="id_ed25519"
            )

        if "rsa" in types:
            rsa_private_key = AsymmetricKeyGenerator.generate_rsa_key(
                seed_phrase,
                key_size=4096,
                context=f"{context_base}/rsa4096"
            )
            rsa_priv, rsa_pub, rsa_fp = cls.serialize_keypair(rsa_private_key)
            result["rsa"] = SSHKeyInfo(
                private_key=rsa_priv,
                public_key=f"{rsa_pub.strip()} {hostname}@{index}-rsa",
                fingerprint_sha256=rsa_fp,
                algorithm="RSA",
                use_case="Legacy compatibility, older SSH servers/clients",
                key_size="4096-bit",
                deterministic=deterministic,
                filename="id_rsa"
            )

        if "ecdsa" in types:
            ecdsa_private_key = AsymmetricKeyGenerator.generate_ec_key(
                seed_phrase,
                curve_name="secp256r1",
                context=f"{context_base}/ecdsa-secp256r1"
            )
            ecdsa_priv, ecdsa_pub, ecdsa_fp = cls.serialize_keypair(ecdsa_private_key)
            result["ecdsa"] = SSHKeyInfo(
                private_key=ecdsa_priv,
                public_key=f"{ecdsa_pub.strip()} {hostname}@{index}-ecdsa",
                fingerprint_sha256=ecdsa_fp,
                algorithm="ECDSA (P-256)",
                use_case="Balanced security/performance, NIST standard",
                key_size="256-bit curve",
                deterministic=deterministic,
                filename="id_ecdsa"
            )

        if "dsa" in types:
            # Note: SSH only supports 1024-bit DSA keys (deprecated for security)
            dsa_private_key = AsymmetricKeyGenerator.generate_dsa_key(
                seed_phrase,
                key_size=1024,
                context=f"{context_base}/dsa1024"
            )
            dsa_priv, dsa_pub, dsa_fp = cls.serialize_keypair(dsa_private_key)
            result["dsa"] = SSHKeyInfo(
                private_key=dsa_priv,
                public_key=f"{dsa_pub.strip()} {hostname}@{index}-dsa",
                fingerprint_sha256=dsa_fp,
                algorithm="DSA",
                use_case="Legacy compatibility only (deprecated/insecure, use Ed25519/RSA)",
                key_size="1024-bit (SSH limitation)",
                deterministic=deterministic,
                filename="id_dsa"
            )

        return result

# ============================================================================
# SSH Certificate Manager
# ============================================================================

class SSHCertificateManager:
    """
    Class methods for SSH certificate generation and management.

    Provides SSH certificate generation with support for user and host
    certificates, various key types, and comprehensive certificate configuration.
    """

    @classmethod
    def load_ssh_ca_bundle(cls, ca_input: str) -> tuple[rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey, str]:
        """
        Load SSH CA private key from bundle (file, stdin, fd, or environment).

        Expected input format (JSON):
        {
          "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----...",
          "public_key": "ssh-ed25519 AAAA..."
        }

        Also supports X.509 bundle format (will extract the key).

        Args:
            ca_input: Bundle source specifier (raw value, '-', '@file', 'fd:<num>', 'env:<NAME>')

        Returns:
            Tuple of (CA private key, CA public key string)

        Raises:
            ValueError: If input is invalid or cannot be parsed
        """
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

        # Extract private key PEM
        if 'private_key' not in ca_data:
            raise ValueError("CA bundle missing 'private_key' field")

        key_pem = ca_data['private_key']

        # Load private key (support both SSH and X.509 formats)
        try:
            # Try SSH format first
            ca_key = serialization.load_ssh_private_key(
                key_pem.encode('utf-8'),
                password=None,
                backend=default_backend()
            )
        except Exception:
            # Try PEM format (X.509 bundle)
            try:
                ca_key = serialization.load_pem_private_key(
                    key_pem.encode('utf-8'),
                    password=None,
                    backend=default_backend()
                )
            except Exception as e:
                raise ValueError(f"Failed to load CA private key: {e}")

        # Get public key string
        if 'public_key' in ca_data:
            public_key_str = ca_data['public_key']
        else:
            # Generate from private key
            public_key = ca_key.public_key()
            public_key_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH
            )
            public_key_str = public_key_bytes.decode('utf-8')

        return ca_key, public_key_str

    @classmethod
    def build_ssh_certificate(cls,
        public_key: rsa.RSAPublicKey | ec.EllipticCurvePublicKey | ed25519.Ed25519PublicKey,
        ca_private_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey,
        cert_config: SSHCertConfig
    ) -> bytes:
        """
        Build SSH certificate using SSHCertificateBuilder.

        Args:
            public_key: Subject's public key to be certified
            ca_private_key: CA private key for signing
            cert_config: SSH certificate configuration

        Returns:
            SSH certificate bytes (OpenSSH format)
        """
        # Map cert type
        cert_type = SSHCertificateType.USER if cert_config.cert_type == "user" else SSHCertificateType.HOST

        # Build certificate
        builder = SSHCertificateBuilder()
        builder = builder.public_key(public_key)
        builder = builder.type(cert_type)
        builder = builder.valid_after(cert_config.valid_from)
        builder = builder.valid_before(cert_config.valid_to)
        builder = builder.key_id(cert_config.key_id.encode('utf-8'))

        # Add principals
        principals_bytes = [p.encode('utf-8') for p in cert_config.principals]
        builder = builder.valid_principals(principals_bytes)

        # Add serial if specified
        if cert_config.serial is not None:
            builder = builder.serial(cert_config.serial)

        # Add critical options (for user certs)
        if cert_config.source_address:
            builder = builder.add_critical_option(
                b"source-address",
                cert_config.source_address.encode('utf-8')
            )
        if cert_config.force_command:
            builder = builder.add_critical_option(
                b"force-command",
                cert_config.force_command.encode('utf-8')
            )

        # Add standard extensions (commonly used for both user and host certs)
        # Default extensions for user certs
        if cert_config.cert_type == "user":
            default_extensions = {
                "permit-X11-forwarding": "",
                "permit-agent-forwarding": "",
                "permit-port-forwarding": "",
                "permit-pty": "",
                "permit-user-rc": ""
            }
            # Merge with custom extensions
            all_extensions = {**default_extensions, **cert_config.extensions}
        else:
            all_extensions = cert_config.extensions

        # Add extensions
        for key, value in all_extensions.items():
            builder = builder.add_extension(
                key.encode('utf-8'),
                value.encode('utf-8')
            )

        # Sign and return
        return builder.sign(ca_private_key).public_bytes()

# ============================================================================
# Command: SSH Keys
# ============================================================================

@cli.command(name='derive-ssh-key')
@click.option(
    '--hostname', '-h',
    required=True,
    help='Target hostname for the SSH key'
)
@click.option(
    '--seed', '-s',
    default=None,
    help='Optional seed phrase for deterministic key derivation (supports -, @file, fd:<N>, env:<NAME>)'
)
@click.option(
    '--index', '-i',
    default=0,
    type=int,
    help='Key index (for multiple keys per host)',
    show_default=True
)
@click.option(
    '--pretty', '-p',
    is_flag=True,
    help='Pretty-print JSON output'
)
@click.option(
    '--all-types', '-a',
    is_flag=True,
    help='Generate all common SSH key types (Ed25519, RSA, ECDSA, DSA)'
)
def derive_ssh_key(hostname, seed, index, pretty, all_types):
    """
    Generate SSH keypairs using optional deterministic derivation.

    By default generates Ed25519 (deterministic, recommended).
    Use --all-types to generate Ed25519, RSA-4096, ECDSA-P256, and DSA-1024.

    Note: DSA is deprecated and insecure. SSH only supports 1024-bit DSA keys.

    All keys include SHA256 fingerprints (same format as ssh-keygen -E sha256).

    Output format is always consistent: a 'keys' dictionary containing key type names
    as keys and key information as values, regardless of single or all-types mode.

    Examples:

      \b
      # Generate Ed25519 key (deterministic, recommended)
      crypto-tools derive-ssh-key --hostname server1 --seed "my-master-seed"

      \b
      # Generate all key types (Ed25519, RSA, ECDSA, DSA)
      crypto-tools derive-ssh-key -h server1 -s "seed" --all-types

      \b
      # Multiple keys for same host (different indices)
      crypto-tools derive-ssh-key -h server1 -s "seed" -i 0  # First key
      crypto-tools derive-ssh-key -h server1 -s "seed" -i 1  # Second key

      \b
      # Extract specific key type (works for both single and all-types mode)
      crypto-tools derive-ssh-key -h server1 -s "seed" | jq -r '.keys.ed25519.public_key'
      crypto-tools derive-ssh-key -h server1 -s "seed" -a | jq -r '.keys.rsa.public_key'

      \b
      # View fingerprints
      crypto-tools derive-ssh-key -h server1 -s "seed" -a | jq -r '.keys[].fingerprint_sha256'

      \b
      # Save all keys to files
      crypto-tools derive-ssh-key -h web1 -s "seed" -a > web1_keys.json
      jq -r '.keys.ed25519.private_key' web1_keys.json > id_ed25519
      jq -r '.keys.ed25519.public_key' web1_keys.json > id_ed25519.pub
      jq -r '.keys.rsa.private_key' web1_keys.json > id_rsa
      jq -r '.keys.rsa.public_key' web1_keys.json > id_rsa.pub
    """
    entropy_metrics = None
    if seed is not None:
        try:
            seed = InputLoader.load_text(seed, description="seed phrase", strip=True)
        except ValueError as e:
            click.echo(f"Error loading seed phrase: {e}", err=True)
            sys.exit(1)

        _, entropy_metrics = SSHKeyManager.derive_ssh_seed(seed, hostname, index)

    # Determine which key types to generate
    if all_types:
        key_types = ["ed25519", "rsa", "ecdsa", "dsa"]
        recommended = "ed25519"
        all_types_list = key_types
    else:
        key_types = ["ed25519"]
        recommended = None
        all_types_list = None

    if seed is not None:
        note = (
            "All keys derived deterministically from the provided seed phrase."
            if all_types
            else "BIP39-inspired derivation - same seed+hostname+index always produces the same keypair"
        )
    else:
        note = "Keys generated using random system entropy (no seed provided)."

    # Generate keys using unified method
    generated_keys = SSHKeyManager.generate_all_ssh_keys(seed, hostname, index, key_types)

    # Build metadata
    metadata = SSHKeyMetadata(
        derivation_path=f"{hostname}/{index}" if seed is not None else "random",
        derivation_method="PBKDF2-HMAC-SHA512" if seed is not None else "system-random",
        iterations=2048 if seed is not None else 0,
        note=note,
        recommended=recommended,
        all_types=all_types_list,
        seed_entropy=EntropyMetrics(**entropy_metrics) if entropy_metrics else None
    )

    # Create SSHKeyOutput model - always use keys dictionary format
    ssh_output = SSHKeyOutput(
        hostname=hostname,
        index=index,
        keys=generated_keys,
        _metadata=metadata
    )

    output = ssh_output.model_dump(by_alias=True, exclude_none=True)

    # Output JSON
    if pretty:
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(json.dumps(output))

# ============================================================================
# Command: SSH CA Bundle
# ============================================================================

@cli.command(name='bundle-ssh-ca')
@click.option(
    '--private-key', '-k',
    required=True,
    help='SSH CA private key file (PEM or OpenSSH format)'
)
@click.option(
    '--public-key', '-u',
    help='SSH CA public key file (optional, will be generated from private key if not provided)'
)
@click.option(
    '--pretty', '-p',
    is_flag=True,
    help='Pretty-print JSON output'
)
def bundle_ssh_ca(private_key, public_key, pretty):
    """
    Bundle SSH CA private and public keys into JSON format.

    Converts separate SSH private and public key files into the JSON format
    required for SSH certificate signing. This is useful for creating SSH CA
    bundles from existing key files.

    \b
    Examples:

      \b
      # Bundle SSH CA from separate files
      crypto-tools bundle-ssh-ca -k ca_key -p ca_key.pub

      \b
      # Bundle SSH CA (generate public key from private key)
      crypto-tools bundle-ssh-ca -k ca_key

      \b
      # Bundle SSH CA with pretty output
      crypto-tools bundle-ssh-ca -k ca_key -p ca_key.pub --pretty

      \b
      # Use bundled CA for SSH certificate signing
      crypto-tools bundle-ssh-ca -k ca_key > ssh_ca.json
      # Then use ssh_ca.json with SSH certificate commands
    """
    # Read private key file
    try:
        with open(private_key, 'r') as f:
            private_key_pem = f.read().strip()
    except FileNotFoundError:
        click.echo(f"Error: Private key file not found: {private_key}", err=True)
        sys.exit(1)
    except IOError as e:
        click.echo(f"Error reading private key file: {e}", err=True)
        sys.exit(1)

    # Read public key file if provided
    public_key_str = None
    if public_key:
        try:
            with open(public_key, 'r') as f:
                public_key_str = f.read().strip()
        except FileNotFoundError:
            click.echo(f"Error: Public key file not found: {public_key}", err=True)
            sys.exit(1)
        except IOError as e:
            click.echo(f"Error reading public key file: {e}", err=True)
            sys.exit(1)
    else:
        # Generate public key from private key
        try:
            # Load private key
            ca_key = serialization.load_ssh_private_key(
                private_key_pem.encode('utf-8'),
                password=None,
                backend=default_backend()
            )

            # Generate public key
            public_key_obj = ca_key.public_key()
            public_key_bytes = public_key_obj.public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH
            )
            public_key_str = public_key_bytes.decode('utf-8')
        except Exception as e:
            click.echo(f"Error generating public key from private key: {e}", err=True)
            sys.exit(1)

    # Determine key type
    try:
        ca_key = serialization.load_ssh_private_key(
            private_key_pem.encode('utf-8'),
            password=None,
            backend=default_backend()
        )

        if isinstance(ca_key, rsa.RSAPrivateKey):
            key_type = f"rsa{ca_key.key_size}"
        elif isinstance(ca_key, ec.EllipticCurvePrivateKey):
            curve_name = ca_key.curve.name
            key_type = f"ec{ca_key.curve.key_size}({curve_name})"
        elif isinstance(ca_key, ed25519.Ed25519PrivateKey):
            key_type = "ed25519"
        else:
            key_type = "unknown"
    except Exception:
        key_type = "unknown"

    # Build metadata
    metadata = SSHBundleMetadata(
        bundled_from_files=True,
        key_type=key_type,
        public_key_generated=public_key is None
    )

    # Create SSH bundle output
    bundle_output = SSHBundleOutput(
        private_key=private_key_pem,
        public_key=public_key_str,
        metadata=metadata
    )

    output = bundle_output.model_dump(by_alias=True)

    # Output JSON
    if pretty:
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(json.dumps(output))

# ============================================================================
# Command: SSH Certificate Generation
# ============================================================================

@cli.command(name='derive-ssh-cert')
@click.option(
    '--hostname', '-h',
    required=True,
    help='Target hostname for the SSH certificate'
)
@click.option(
    '--seed', '-s',
    default=None,
    help='Optional seed phrase for deterministic key derivation (supports -, @file, fd:<N>, env:<NAME>)'
)
@click.option(
    '--index', '-i',
    default=0,
    type=int,
    help='Key index (for multiple certificates per host)',
    show_default=True
)
@click.option(
    '--cert-type', '-t',
    type=click.Choice(['user', 'host']),
    default='host',
    help='Certificate type (user or host)',
    show_default=True
)
@click.option(
    '--principals', '-n',
    multiple=True,
    help='Valid principals (usernames or hostnames). Can be specified multiple times.'
)
@click.option(
    '--valid-days', '-d',
    default=30,
    type=int,
    help='Certificate validity in days',
    show_default=True
)
@click.option(
    '--valid-from',
    help='Valid-from timestamp (Unix epoch seconds or ISO format). Defaults to now.'
)
@click.option(
    '--valid-to',
    help='Valid-to timestamp (Unix epoch seconds or ISO format). Defaults to now + valid-days.'
)
@click.option(
    '--serial',
    type=int,
    help='Optional serial number (0 to 2^64-1). Defaults to deterministic from seed.'
)
@click.option(
    '--source-address',
    help='Source address restriction (CIDR format, user certs only)'
)
@click.option(
    '--force-command',
    help='Force command (user certs only)'
)
@click.option(
    '--sign-with', '-w',
    required=True,
    help='SSH CA bundle file or \'-\' for stdin (JSON format from bundle-ssh-ca)'
)
@click.option(
    '--key-type', '-k',
    type=click.Choice(['ed25519', 'rsa2048', 'rsa4096', 'ec256', 'ec384']),
    default='ed25519',
    help='Private key type for the certificate',
    show_default=True
)
@click.option(
    '--pretty', '-p',
    is_flag=True,
    help='Pretty-print JSON output'
)
def derive_ssh_cert(
    hostname, seed, index, cert_type, principals, valid_days, valid_from, valid_to,
    serial, source_address, force_command, sign_with, key_type, pretty
):
    """
    Generate SSH certificates with optional deterministic derivation and CA signing.

    When a seed phrase is provided, private keys and serial numbers are derived
    deterministically. Otherwise, fresh randomness is used for each certificate.

    \b
    Examples:

      \b
      # Generate host certificate for a server
      crypto-tools derive-ssh-cert -h server1.example.com -s "myseed" \\
        --sign-with ca_bundle.json --principals server1.example.com \\
        --principals server1 --valid-days 90

      \b
      # Generate user certificate for a specific user
      crypto-tools derive-ssh-cert -h alice -s "myseed" \\
        --cert-type user --sign-with ca_bundle.json \\
        --principals alice --principals admin --valid-days 7

      \b
      # Generate certificate with custom validity period
      crypto-tools derive-ssh-cert -h web1 -s "myseed" \\
        --sign-with ca_bundle.json --principals web1.example.com \\
        --valid-from "2024-01-01T00:00:00Z" --valid-to "2024-12-31T23:59:59Z"

      \b
      # Generate certificate with source address restriction (user certs)
      crypto-tools derive-ssh-cert -h deploy -s "myseed" \\
        --cert-type user --sign-with ca_bundle.json \\
        --principals deploy --source-address "192.168.1.0/24" \\
        --force-command "/usr/local/bin/deploy.sh"

      \b
      # Use CA bundle from stdin
      crypto-tools bundle-ssh-ca -k ca_key | \\
        crypto-tools derive-ssh-cert -h server1 -s "myseed" \\
          --sign-with - --principals server1.example.com

      \b
      # Extract certificate and private key
      crypto-tools derive-ssh-cert -h server1 -s "myseed" \\
        --sign-with ca_bundle.json --principals server1.example.com | \\
        jq -r '.certificate' > server1-cert.pub
      crypto-tools derive-ssh-cert -h server1 -s "myseed" \\
        --sign-with ca_bundle.json --principals server1.example.com | \\
        jq -r '.private_key' > server1_key
    """
    # Load CA bundle
    try:
        ca_key, ca_public_key = SSHCertificateManager.load_ssh_ca_bundle(sign_with)
    except ValueError as e:
        click.echo(f"Error loading CA bundle: {e}", err=True)
        sys.exit(1)

    if seed is not None:
        try:
            seed = InputLoader.load_text(seed, description="seed phrase", strip=True)
        except ValueError as e:
            click.echo(f"Error loading seed phrase: {e}", err=True)
            sys.exit(1)

    # Set default principals if none provided
    if not principals:
        if cert_type == "host":
            principals = [hostname]
        else:
            principals = [hostname]  # Use hostname as username for user certs

    # Parse timestamps
    now = int(time.time())
    if valid_from:
        try:
            parsed_valid_from_dt = parse_timestamp(valid_from)
            parsed_valid_from = int(parsed_valid_from_dt.timestamp())
        except ValueError as e:
            click.echo(f"Error parsing --valid-from: {e}", err=True)
            sys.exit(1)
    else:
        parsed_valid_from = now

    if valid_to:
        try:
            parsed_valid_to_dt = parse_timestamp(valid_to)
            parsed_valid_to = int(parsed_valid_to_dt.timestamp())
        except ValueError as e:
            click.echo(f"Error parsing --valid-to: {e}", err=True)
            sys.exit(1)
    else:
        parsed_valid_to = parsed_valid_from + (valid_days * 24 * 60 * 60)

    # Derive serial number if not provided
    serial_derived = False
    if serial is None:
        context = f"ssh-cert/{hostname}/{index}"
        if seed is not None:
            derived_seed_serial = SeedDerivation.derive_master_seed(
                seed_phrase=seed,
                salt_phrase=f"{context}/serial",
                iterations=2048,
                dklen=32
            )
            serial_bytes = derived_seed_serial[:8]
            serial = int.from_bytes(serial_bytes, byteorder='big') % (2**64)
            serial_derived = True
        else:
            serial = secrets.randbits(64)
            if serial == 0:
                serial = 1

    # Create derivation context for key generation
    key_context = f"ssh-key/{hostname}/{index}"

    if seed is not None:
        derived_seed, entropy_metrics = SeedDerivation.derive_entropy_seed(
            seed_phrase=seed,
            salt_phrase=key_context,
            dklen=64
        )
        seed_input = derived_seed
    else:
        derived_seed = None
        entropy_metrics = None
        seed_input = None

    # Generate private key based on key type
    if key_type == "ed25519":
        private_key = AsymmetricKeyGenerator.generate_ed25519_key(
            seed_input,
            context=f"{key_context}/ed25519"
        )
    elif key_type.startswith("rsa"):
        key_size = int(key_type[3:])
        private_key = AsymmetricKeyGenerator.generate_rsa_key(
            seed_input,
            key_size=key_size,
            context=f"{key_context}/rsa{key_size}" if seed is not None else None
        )
    elif key_type.startswith("ec"):
        key_size = int(key_type[2:])
        curve_map = {256: "secp256r1", 384: "secp384r1", 521: "secp521r1"}
        curve_name = curve_map.get(key_size, "secp256r1")
        private_key = AsymmetricKeyGenerator.generate_ec_key(
            seed_input,
            curve_name,
            context=f"{key_context}/{curve_name}" if seed is not None else None
        )
    else:
        click.echo(f"Error: Unsupported key type: {key_type}", err=True)
        sys.exit(1)

    # Get public key
    public_key = private_key.public_key()

    # Build certificate configuration
    cert_config = SSHCertConfig(
        cert_type=cert_type,
        key_id=f"{hostname}@{index}",
        principals=list(principals),
        valid_from=parsed_valid_from,
        valid_to=parsed_valid_to,
        serial=serial,
        source_address=source_address,
        force_command=force_command,
        extensions={}
    )

    # Build SSH certificate
    try:
        certificate_bytes = SSHCertificateManager.build_ssh_certificate(
            public_key, ca_key, cert_config
        )
    except Exception as e:
        click.echo(f"Error building SSH certificate: {e}", err=True)
        sys.exit(1)

    # Serialize private key to OpenSSH format
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    # Convert certificate bytes to string
    certificate_str = certificate_bytes.decode('utf-8')

    # Build metadata
    metadata = SSHCertMetadata(
        derivation_path=key_context if seed is not None else "random",
        derivation_method="PBKDF2-HMAC-SHA512" if seed is not None else "system-random",
        iterations=2048 if seed is not None else 0,
        key_type=key_type,
        cert_type=cert_type,
        ca_signed=True,
        deterministic_serial=serial_derived,
        deterministic_key=seed is not None,
        seed_entropy=EntropyMetrics(**entropy_metrics) if entropy_metrics else None
    )

    # Create SSH certificate output
    cert_output = SSHCertOutput(
        private_key=private_key_pem,
        certificate=certificate_str,
        public_key=public_key.public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH
        ).decode('utf-8'),
        ca_public_key=ca_public_key,
        cert_type=cert_type,
        key_id=cert_config.key_id,
        principals=list(principals),
        valid_from=parsed_valid_from,
        valid_to=parsed_valid_to,
        serial_number=serial,
        source_address=source_address,
        force_command=force_command,
        metadata=metadata
    )

    output = cert_output.model_dump(by_alias=True)

    # Output JSON
    if pretty:
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(json.dumps(output))
