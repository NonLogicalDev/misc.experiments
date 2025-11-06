"""
Password hash generation tools.

This module provides:
- Password hash generation for various authentication systems
- Support for bcrypt, APR MD5, SHA crypt variants, Argon2
- Deterministic hashing with seed phrases for Infrastructure-as-Code
- CLI command for generating password hashes
"""

# Standard library imports
import sys
import json
import hashlib
import base64
from getpass import getpass
from typing import Optional, Dict

# Third-party imports
import click
import bcrypt
from argon2 import PasswordHasher
from argon2.low_level import Type, hash_secret_raw
from passlib.hash import (
    apr_md5_crypt,
    sha256_crypt,
    sha512_crypt,
    md5_crypt,
)
from pydantic import BaseModel, Field, ConfigDict

# Local imports
from degen_crypto.lib_common import (
    cli,
    EntropyAnalyzer,
    SeedDerivation,
    DerivationInfo,
    EntropyMetrics,
    InputLoader,
)


# ============================================================================
# Password Pydantic Models
# ============================================================================

class PasswordMetadata(BaseModel):
    """Metadata for password hash generation."""

    deterministic: bool = Field(..., description="Whether hashes are deterministic")
    note: Optional[str] = Field(default=None, description="Additional notes")
    seed_phrase_used: Optional[str] = Field(default=None, description="Seed phrase used for deterministic generation")
    derivation: Optional[DerivationInfo] = Field(default=None, description="Derivation information")
    seed_entropy: Optional[EntropyMetrics] = Field(default=None, description="Entropy metrics of the seed phrase")

class PasswordHashOutput(BaseModel):
    """Complete password hash output with all hash types and metadata."""

    model_config = ConfigDict(populate_by_name=True)

    hashes: Dict[str, str] = Field(..., description="Dictionary of all password hashes")
    metadata: PasswordMetadata = Field(..., alias="_metadata", description="Generation metadata")

class UseCaseInfo(BaseModel):
    """Information about a specific use case."""

    model_config = ConfigDict(populate_by_name=True)

    use_case: str = Field(..., description="Use case name")
    recommended: str = Field(..., description="Recommended algorithm")
    format: str = Field(..., description="Expected format")
    note: str = Field(..., description="Additional notes")
    hashes: Dict[str, str] = Field(..., description="Relevant hashes for this use case")
    metadata: Optional[PasswordMetadata] = Field(default=None, alias="_metadata", description="Generation metadata")


# ============================================================================
# Password Hashing Module
# ============================================================================

class PasswordHashGenerator:
    """
    Class methods for generating password hashes using various algorithms.

    Supports deterministic hashing with seed phrases and provides
    comprehensive hash generation for different authentication systems.
    """

    @classmethod
    def generate_deterministic_salt(cls, seed_phrase: str, context: str, length: int = 16) -> bytes:
        """
        Generate a deterministic salt from a seed phrase and context.

        Args:
            seed_phrase: The user-provided seed phrase
            context: Context string (e.g., 'bcrypt', 'sha512_crypt')
            length: Desired salt length in bytes

        Returns:
            Deterministic salt bytes
        """
        # Combine seed phrase with context to get different salts per algorithm
        combined = f"{seed_phrase}:{context}".encode('utf-8')
        # Use SHA-256 to generate deterministic bytes
        salt_hash = hashlib.sha256(combined).digest()
        # Extend if needed by hashing again
        while len(salt_hash) < length:
            salt_hash += hashlib.sha256(salt_hash + combined).digest()
        return salt_hash[:length]

    @classmethod
    def encode_bcrypt_salt(cls, salt_bytes: bytes) -> str:
        """
        Encode bytes into bcrypt's base64 format (22 characters).

        Args:
            salt_bytes: 16 bytes of salt data

        Returns:
            22-character bcrypt-compatible salt string
        """
        bcrypt_alphabet = "./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

        # Properly encode 16 bytes into 22 base64 characters (bcrypt format)
        # Process in groups of 3 bytes -> 4 chars
        encoded = []
        for i in range(0, 15, 3):  # 0, 3, 6, 9, 12
            b1, b2, b3 = salt_bytes[i], salt_bytes[i+1], salt_bytes[i+2]
            encoded.append(bcrypt_alphabet[b1 >> 2])
            encoded.append(bcrypt_alphabet[((b1 & 0x03) << 4) | (b2 >> 4)])
            encoded.append(bcrypt_alphabet[((b2 & 0x0f) << 2) | (b3 >> 6)])
            encoded.append(bcrypt_alphabet[b3 & 0x3f])

        # Handle the last byte (16th byte, index 15)
        b1 = salt_bytes[15]
        encoded.append(bcrypt_alphabet[b1 >> 2])
        encoded.append(bcrypt_alphabet[(b1 & 0x03) << 4])

        return ''.join(encoded)

    @classmethod
    def encode_crypt_salt(cls, salt_bytes: bytes, length: int) -> str:
        """
        Encode bytes into passlib-compatible salt format.
        Passlib salts only accept [./0-9A-Za-z]

        Args:
            salt_bytes: Raw salt bytes
            length: Desired salt string length

        Returns:
            Salt string compatible with passlib crypt functions
        """
        salt_str = base64.b64encode(salt_bytes).decode('ascii')
        # Replace invalid characters for passlib
        salt_str = salt_str.replace('+', '.').replace('/', '.').replace('=', '')
        return salt_str[:length]


    @classmethod
    def generate_bcrypt_hash(cls, password: str, seed_phrase: Optional[str] = None) -> str:
        """Generate bcrypt hash (cost factor 12)."""
        if seed_phrase:
            # Use unified PBKDF2 derivation
            det_salt, _ = SeedDerivation.derive_entropy_seed(
                seed_phrase=seed_phrase,
                salt_phrase="password/bcrypt",
                dklen=16
            )
            encoded_salt = cls.encode_bcrypt_salt(det_salt)
            bcrypt_salt = f"$2b$12${encoded_salt}".encode('ascii')
            return bcrypt.hashpw(password.encode('utf-8'), bcrypt_salt).decode('utf-8')
        else:
            return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')

    @classmethod
    def generate_apr_md5_hash(cls, password: str, seed_phrase: Optional[str] = None) -> str:
        """Generate Apache APR1 MD5 hash."""
        if seed_phrase:
            det_salt, _ = SeedDerivation.derive_entropy_seed(
                seed_phrase=seed_phrase,
                salt_phrase="password/apr_md5",
                dklen=8
            )
            salt_str = cls.encode_crypt_salt(det_salt, 8)
            return apr_md5_crypt.using(salt=salt_str).hash(password)
        else:
            return apr_md5_crypt.hash(password)

    @classmethod
    def generate_sha256_crypt_hash(cls, password: str, seed_phrase: Optional[str] = None) -> str:
        """Generate SHA-256 crypt hash (5000 rounds)."""
        if seed_phrase:
            det_salt, _ = SeedDerivation.derive_entropy_seed(
                seed_phrase=seed_phrase,
                salt_phrase="password/sha256_crypt",
                dklen=16
            )
            salt_str = cls.encode_crypt_salt(det_salt, 16)
            return sha256_crypt.using(rounds=5000, salt=salt_str).hash(password)
        else:
            return sha256_crypt.using(rounds=5000).hash(password)

    @classmethod
    def generate_sha512_crypt_hash(cls, password: str, seed_phrase: Optional[str] = None) -> str:
        """Generate SHA-512 crypt hash (5000 rounds)."""
        if seed_phrase:
            det_salt, _ = SeedDerivation.derive_entropy_seed(
                seed_phrase=seed_phrase,
                salt_phrase="password/sha512_crypt",
                dklen=16
            )
            salt_str = cls.encode_crypt_salt(det_salt, 16)
            return sha512_crypt.using(rounds=5000, salt=salt_str).hash(password)
        else:
            return sha512_crypt.using(rounds=5000).hash(password)

    @classmethod
    def generate_md5_crypt_hash(cls, password: str, seed_phrase: Optional[str] = None) -> str:
        """Generate MD5 crypt hash (legacy)."""
        if seed_phrase:
            det_salt, _ = SeedDerivation.derive_entropy_seed(
                seed_phrase=seed_phrase,
                salt_phrase="password/md5_crypt",
                dklen=8
            )
            salt_str = cls.encode_crypt_salt(det_salt, 8)
            return md5_crypt.using(salt=salt_str).hash(password)
        else:
            return md5_crypt.hash(password)

    @classmethod
    def generate_sha1_hash(cls, password: str) -> str:
        """Generate SHA-1 hash compatible with htpasswd -s."""
        sha1_digest = hashlib.sha1(password.encode('utf-8')).digest()
        b64_hash = base64.b64encode(sha1_digest).decode('ascii')
        return f"{{SHA}}{b64_hash}"

    @classmethod
    def generate_argon2_hash(cls, password: str, seed_phrase: Optional[str] = None) -> str:
        """Generate Argon2id hash."""
        if seed_phrase:
            det_salt, _ = SeedDerivation.derive_entropy_seed(
                seed_phrase=seed_phrase,
                salt_phrase="password/argon2",
                dklen=16
            )
            argon2_raw = hash_secret_raw(
                secret=password.encode('utf-8'),
                salt=det_salt,
                time_cost=2,
                memory_cost=65536,
                parallelism=1,
                hash_len=32,
                type=Type.ID
            )
            # Format as argon2id hash string
            return f"$argon2id$v=19$m=65536,t=2,p=1${base64.b64encode(det_salt).decode('ascii').rstrip('=')}${base64.b64encode(argon2_raw).decode('ascii').rstrip('=')}"
        else:
            ph = PasswordHasher(
                time_cost=2,
                memory_cost=65536,
                parallelism=1,
                hash_len=32,
                salt_len=16
            )
            return ph.hash(password)

    @classmethod
    def generate_md5_legacy_hash(cls, password: str) -> str:
        """Generate plain MD5 hash (insecure, for legacy only)."""
        md5_digest = hashlib.md5(password.encode('utf-8')).digest()
        b64_hash = base64.b64encode(md5_digest).decode('ascii')
        return f"{{MD5}}{b64_hash}"

    @classmethod
    def generate_all_hashes(cls, password: str, seed_phrase: Optional[str] = None) -> PasswordHashOutput:
        """
        Generate all password hashes for various authentication systems.

        Args:
            password: The password to hash
            seed_phrase: Optional seed phrase for deterministic hashing

        Returns:
            PasswordHashOutput with all hash variants and metadata
        """
        # Get entropy metrics if seed phrase is provided
        entropy_metrics = None
        if seed_phrase:
            entropy_metrics = EntropyAnalyzer.calculate_entropy_metrics(seed_phrase)

        # Generate all hash types
        bcrypt_hash = cls.generate_bcrypt_hash(password, seed_phrase)
        apr_md5_hash = cls.generate_apr_md5_hash(password, seed_phrase)
        sha256_hash = cls.generate_sha256_crypt_hash(password, seed_phrase)
        sha512_hash = cls.generate_sha512_crypt_hash(password, seed_phrase)
        md5crypt_hash = cls.generate_md5_crypt_hash(password, seed_phrase)
        sha1_hash = cls.generate_sha1_hash(password)
        argon2_hash = cls.generate_argon2_hash(password, seed_phrase)
        md5_legacy = cls.generate_md5_legacy_hash(password)

        # Build metadata
        metadata = PasswordMetadata(deterministic=seed_phrase is not None)

        if seed_phrase:
            metadata.note = "Hashes generated with deterministic salt - same password and seed will always produce same hashes"
            metadata.seed_phrase_used = seed_phrase
            metadata.derivation = DerivationInfo(
                method="PBKDF2-HMAC-SHA512",
                iterations=2048,
                salt_prefix="crypto-tools/password"
            )
            if entropy_metrics:
                metadata.seed_entropy = EntropyMetrics(**entropy_metrics)

        return PasswordHashOutput(
            hashes={
                "bcrypt": bcrypt_hash,
                "apr_md5": apr_md5_hash,
                "sha256_crypt": sha256_hash,
                "sha512_crypt": sha512_hash,
                "md5_crypt": md5crypt_hash,
                "sha1": sha1_hash,
                "argon2": argon2_hash,
                "md5_legacy": md5_legacy,
            },
            _metadata=metadata
        )


# ============================================================================
# Helper Functions
# ============================================================================

def get_password_input(from_stdin: bool = False) -> str:
    """Get password from stdin or interactive prompt."""
    if from_stdin or not sys.stdin.isatty():
        password = sys.stdin.read().strip()
        if not password:
            click.echo("Error: No password provided on stdin!", err=True)
            sys.exit(1)
        return password
    else:
        password = getpass("Enter password: ")
        if not password:
            click.echo("Error: Password cannot be empty!", err=True)
            sys.exit(1)

        password_confirm = getpass("Confirm password: ")
        if password != password_confirm:
            click.echo("Error: Passwords do not match!", err=True)
            sys.exit(1)

        return password


# ============================================================================
# CLI Command
# ============================================================================

@cli.command(name='derive-passwd-set')
@click.option(
    '--username', '-u',
    default='admin',
    help='Username for htpasswd entry',
    show_default=True
)
@click.option(
    '--pretty', '-p',
    is_flag=True,
    help='Pretty-print JSON output'
)
@click.option(
    '--use-case', '-c',
    type=click.Choice(['traefik', 'portainer', 'apache', 'nginx', 'linux', 'nixos', 'all']),
    help='Show guidance for specific use case'
)
@click.option(
    '--seed', '-s',
    default=None,
    help='Seed phrase for deterministic hash generation (supports -, @file, fd:<N>, env:<NAME>)'
)
@click.option(
    '--quiet', '-q',
    is_flag=True,
    help='Minimal output - exclude _use_cases and minimize _metadata'
)
def derive_passwd_set(username, pretty, use_case, seed, quiet):
    """
    Generate password hashes for htpasswd, Traefik, Portainer, Linux auth.

    \b
    USE CASES & RECOMMENDED ALGORITHMS:

    Traefik:    bcrypt or apr_md5  (htpasswd format: username:hash)
    Portainer:  bcrypt             (htpasswd format: username:hash)
    Apache:     apr_md5 or bcrypt  (.htpasswd file)
    Nginx:      apr_md5 or sha1    (.htpasswd file)
    Linux:      sha512_crypt       (/etc/shadow)
    NixOS:      sha512_crypt       (users.users.<name>.hashedPassword)

    \b
    SECURITY RATINGS:
    Excellent:  bcrypt, sha512_crypt, argon2
    Good:       apr_md5, sha256_crypt
    Legacy:     md5_crypt, sha1
    INSECURE:   md5_legacy (DO NOT USE)

    \b
    Examples:

      \b
      # Interactive mode
      crypto-tools derive-passwd-set

      \b
      # From stdin
      echo "mypassword" | crypto-tools derive-passwd-set

      \b
      # Custom username
      echo "mypassword" | crypto-tools derive-passwd-set --username bob

      \b
      # For Traefik basic auth
      echo "mypassword" | crypto-tools derive-passwd-set -u admin | jq -r '.hashes.apr_md5'
      # Output: $apr1$... (combine with username: admin:$apr1$...)

      \b
      # For NixOS users.users.<name>.hashedPassword
      echo "mypassword" | crypto-tools derive-passwd-set | jq -r '.hashes.sha512_crypt'
      # Output: $6$... (use in configuration.nix)

      \b
      # Deterministic hashing (reproducible for IaC)
      echo "mypassword" | crypto-tools derive-passwd-set --seed "my-project" | jq -r '.hashes.sha512_crypt'

      \b
      # Quiet mode - minimal metadata
      echo "mypassword" | crypto-tools derive-passwd-set -q | jq -r '.hashes.sha512_crypt'

      \b
      # Show specific use case guidance
      echo "mypassword" | crypto-tools derive-passwd-set --use-case traefik --pretty
    """
    # Get password
    password = get_password_input(from_stdin=not sys.stdin.isatty())

    try:
        seed_loaded = InputLoader.load_text(seed, description="seed phrase", strip=True)
    except ValueError as e:
        click.echo(f"Error loading seed phrase: {e}", err=True)
        sys.exit(1)

    seed = seed_loaded

    # Generate all hashes
    all_hashes = PasswordHashGenerator.generate_all_hashes(password, seed_phrase=seed)

    # Define use case mappings (moved from generate_all_hashes)
    USE_CASE_MAP = {
        "traefik": {
            "recommended": "bcrypt or apr_md5",
            "format": "username:hash (htpasswd format)",
            "fields": ["bcrypt", "apr_md5"],
            "note": "Traefik supports bcrypt and APR1 MD5 for basic auth"
        },
        "portainer": {
            "recommended": "bcrypt",
            "format": "username:hash (htpasswd format)",
            "fields": ["bcrypt"],
            "note": "Portainer uses bcrypt for htpasswd authentication"
        },
        "apache": {
            "recommended": "apr_md5 or bcrypt",
            "format": ".htpasswd file",
            "fields": ["apr_md5", "bcrypt", "sha256_crypt", "sha512_crypt"],
            "note": "Apache 2.4+ supports bcrypt (-B), APR1 MD5 (-m), SHA-256, SHA-512"
        },
        "nginx": {
            "recommended": "apr_md5 or sha1",
            "format": ".htpasswd file",
            "fields": ["apr_md5", "sha1", "sha256_crypt", "sha512_crypt"],
            "note": "Nginx supports APR1 MD5, SHA-1, and crypt formats"
        },
        "linux": {
            "recommended": "sha512_crypt",
            "format": "/etc/shadow",
            "fields": ["sha512_crypt", "sha256_crypt", "md5_crypt"],
            "note": "SHA-512 is recommended for modern Linux systems"
        },
        "nixos": {
            "recommended": "sha512_crypt",
            "format": "users.users.<name>.hashedPassword",
            "fields": ["sha512_crypt", "sha256_crypt"],
            "note": "Use sha512_crypt in NixOS configuration"
        }
    }

    # Filter by use case if specified
    if use_case and use_case != "all":
        use_case_info = USE_CASE_MAP[use_case]
        filtered_hashes = {}
        for field in use_case_info["fields"]:
            if field in all_hashes.hashes:
                filtered_hashes[field] = all_hashes.hashes[field]

        # Create UseCaseInfo model
        use_case_output = UseCaseInfo(
            use_case=use_case,
            recommended=use_case_info["recommended"],
            format=use_case_info["format"],
            note=use_case_info["note"],
            hashes=filtered_hashes,
            _metadata=all_hashes.metadata
        )
        output = use_case_output.model_dump(by_alias=True)
    else:
        output = all_hashes.model_dump(by_alias=True)

    # Apply quiet mode filtering
    if quiet and "_metadata" in output:
        # Minimize _metadata to just essential info
        minimal_metadata = {
            "deterministic": output["_metadata"]["deterministic"]
        }
        if seed:
            minimal_metadata["seed_used"] = True
        output["_metadata"] = minimal_metadata

    # Output JSON
    if pretty:
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(json.dumps(output))
