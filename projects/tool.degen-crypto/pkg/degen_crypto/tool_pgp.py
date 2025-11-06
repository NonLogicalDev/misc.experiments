"""
PGP Identity Generation Utilities

Provides truly deterministic PGP identity generation using deterministic
cryptographic key derivation from seed phrases.

Features:
- ✓ Fully deterministic PGP key generation (RSA, Ed25519, ECDSA)
- ✓ Same seed + context always produces same fingerprint
- ✓ Manual PGP packet construction using deterministic key material
- ✓ Fixed timestamp (2020-01-01) for reproducible fingerprints
- Primary key + subkey generation (signing, encryption, authentication)
- OpenPGP format output (armored ASCII)
- Fingerprint and Key ID calculation
- User ID with name and email
- Configurable key expiration

Implementation Details:
- Generates deterministic cryptographic keys using PBKDF2-HMAC-SHA512
- Manually populates PGP key packets to avoid random key generation
- Uses fixed creation timestamp (2020-01-01 UTC) for determinism
- Supports context separation for multiple keys from same seed

Commands:
- derive-pgp-identity: Generate complete PGP identity with subkeys
- derive-pgp-key: Generate single PGP key (for flexibility)

Note: Keys generated with this tool will have a creation date of 2020-01-01
to ensure deterministic fingerprints. The actual key security is not affected
by this fixed timestamp.
"""

# Standard library imports
import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Literal

# Third-party imports
import click
import pgpy
from pgpy.constants import (
    PubKeyAlgorithm,
    KeyFlags,
    HashAlgorithm,
    SymmetricKeyAlgorithm,
    CompressionAlgorithm,
    EllipticCurveOID,
)
from pgpy.packet.packets import PrivKeyV4
from pgpy.packet.fields import MPI, ECPoint, ECPointFormat
from pydantic import BaseModel, Field, ConfigDict

# Local imports
from degen_crypto.lib_common import cli, EntropyMetrics, EntropyAnalyzer, SeedDerivation, InputLoader, parse_timestamp
from degen_crypto.lib_crypto_asym import AsymmetricKeyGenerator


# ============================================================================
# PGP Pydantic Models
# ============================================================================

class PGPKeyInfo(BaseModel):
    """Information about a single PGP key."""

    fingerprint: str = Field(..., description="Full key fingerprint (40-character hex)")
    key_id: str = Field(..., description="Short key ID (16-character hex)")
    key_type: str = Field(..., description="Key algorithm type")
    key_size: str = Field(..., description="Key size or curve information")
    created: int = Field(..., description="Creation timestamp (Unix epoch seconds)")
    expires: Optional[int] = Field(default=None, description="Expiration timestamp (Unix epoch seconds)")
    usage_flags: List[str] = Field(..., description="Key usage flags")
    public_key_armored: str = Field(..., description="Armored ASCII public key")
    private_key_armored: str = Field(..., description="Armored ASCII private key")


class PGPSubkeyInfo(BaseModel):
    """Information about a PGP subkey."""

    fingerprint: str = Field(..., description="Subkey fingerprint")
    key_id: str = Field(..., description="Subkey ID")
    key_type: str = Field(..., description="Subkey algorithm type")
    purpose: str = Field(..., description="Subkey purpose (signing, encryption, authentication)")
    usage_flags: List[str] = Field(..., description="Key usage flags")


class PGPIdentityMetadata(BaseModel):
    """Metadata for PGP identity generation."""

    derivation_method: str = Field(..., description="Derivation method")
    iterations: int = Field(default=2048, description="PBKDF2 iterations")
    deterministic: bool = Field(default=True, description="Whether generation is deterministic")
    seed_entropy: Optional[EntropyMetrics] = Field(default=None, description="Entropy metrics of the seed phrase")


class PGPIdentityOutput(BaseModel):
    """Complete PGP identity output with primary key and subkeys."""

    model_config = ConfigDict(populate_by_name=True, exclude_none=True)

    user_id: str = Field(..., description="User ID (name and email)")
    primary_key: PGPKeyInfo = Field(..., description="Primary key information")
    subkeys: Optional[List[PGPSubkeyInfo]] = Field(default=None, description="Subkey information")
    public_key_bundle: str = Field(..., description="Complete public key bundle (armored)")
    private_key_bundle: str = Field(..., description="Complete private key bundle (armored)")
    metadata: PGPIdentityMetadata = Field(..., alias="_metadata", description="Generation metadata")


class PGPKeyOutput(BaseModel):
    """Single PGP key output."""

    model_config = ConfigDict(populate_by_name=True, exclude_none=True)

    key_info: PGPKeyInfo = Field(..., description="Key information")
    metadata: PGPIdentityMetadata = Field(..., alias="_metadata", description="Generation metadata")


# ============================================================================
# PGP Utilities
# ============================================================================

# No standalone utility functions currently - all utilities are in PGPIdentityGenerator

# ============================================================================
# PGP Identity Generator
# ============================================================================

class PGPIdentityGenerator:
    """
    Deterministic PGP identity generation using common_asym infrastructure.

    Generates OpenPGP-compliant keys with proper packet structure and metadata.
    """

    @staticmethod
    def parse_key_spec(key_spec: str) -> tuple[str, int | str, str]:
        """
        Parse key specification string into (key_type, key_param, display_string).

        Format: "type:param1:param2:..." where omitted params use defaults.

        Examples:
            "ed25519" -> ("ed25519", None, "Curve25519")
            "rsa" -> ("rsa", 4096, "4096 bits")
            "rsa:2048" -> ("rsa", 2048, "2048 bits")
            "ecdsa" -> ("ecdsa", "secp256r1", "secp256r1")
            "ecdsa:secp384r1" -> ("ecdsa", "secp384r1", "secp384r1")

        Args:
            key_spec: Key specification string

        Returns:
            Tuple of (key_type, key_param, display_string)

        Raises:
            click.BadParameter: If key spec is invalid
        """
        parts = key_spec.split(":")
        key_type = parts[0].lower()

        if key_type == "ed25519":
            return ("ed25519", None, "Curve25519")

        elif key_type == "rsa":
            # Default RSA size is 4096
            key_size = 4096
            if len(parts) > 1:
                try:
                    key_size = int(parts[1])
                    if key_size not in [2048, 4096]:
                        raise click.BadParameter(f"RSA key size must be 2048 or 4096, got {key_size}")
                except ValueError:
                    raise click.BadParameter(f"Invalid RSA key size: {parts[1]}")
            return ("rsa", key_size, f"{key_size} bits")

        elif key_type == "ecdsa":
            # Default ECDSA curve is secp256r1
            curve = "secp256r1"
            if len(parts) > 1:
                curve = parts[1].lower()
                valid_curves = ["secp256r1", "secp384r1", "secp521r1"]
                if curve not in valid_curves:
                    raise click.BadParameter(
                        f"ECDSA curve must be one of {valid_curves}, got {curve}"
                    )
            return ("ecdsa", curve, curve)

        else:
            raise click.BadParameter(
                f"Invalid key type: {key_type}. Must be one of: ed25519, rsa, ecdsa"
            )

    @staticmethod
    def _populate_rsa_key_material(crypto_key, pk: PrivKeyV4):
        """Populate RSA key material in a PrivKeyV4 packet from cryptography key."""
        from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod

        private_numbers = crypto_key.private_numbers()
        public_numbers = private_numbers.public_numbers

        # Populate public key fields
        pk.keymaterial.n = MPI(public_numbers.n)
        pk.keymaterial.e = MPI(public_numbers.e)

        # Populate private key fields
        pk.keymaterial.d = MPI(private_numbers.d)
        pk.keymaterial.p = MPI(private_numbers.p)
        pk.keymaterial.q = MPI(private_numbers.q)

        # Calculate u = p^-1 mod q (multiplicative inverse of p mod q)
        # PGPy's rsa_crt_iqmp normally computes q^-1 mod p, so swap to get p^-1 mod q
        pk.keymaterial.u = MPI(rsa_mod.rsa_crt_iqmp(private_numbers.q, private_numbers.p))

        # Compute checksum
        pk.keymaterial._compute_chksum()

    @staticmethod
    def _populate_ecdsa_key_material(crypto_key, pk: PrivKeyV4, curve_oid: EllipticCurveOID):
        """Populate ECDSA key material in a PrivKeyV4 packet from cryptography key."""
        private_numbers = crypto_key.private_numbers()
        public_numbers = private_numbers.public_numbers

        # Set curve OID
        pk.keymaterial.oid = curve_oid

        # Populate public key point (x, y coordinates)
        pk.keymaterial.p = ECPoint.from_values(
            curve_oid.key_size,
            ECPointFormat.Standard,
            MPI(public_numbers.x),
            MPI(public_numbers.y)
        )

        # Populate private key scalar
        pk.keymaterial.s = MPI(private_numbers.private_value)

        # Compute checksum
        pk.keymaterial._compute_chksum()

    @staticmethod
    def _populate_ed25519_key_material(crypto_key, pk: PrivKeyV4):
        """Populate Ed25519 key material in a PrivKeyV4 packet from cryptography key."""
        from cryptography.hazmat.primitives import serialization

        # Set curve OID
        pk.keymaterial.oid = EllipticCurveOID.Ed25519

        # Get public key bytes (32 bytes for Ed25519)
        public_bytes = crypto_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

        # Get private key bytes (32 bytes seed for Ed25519)
        private_bytes = crypto_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )

        # Populate public key point (native format for Ed25519)
        pk.keymaterial.p = ECPoint.from_values(
            EllipticCurveOID.Ed25519.key_size,
            ECPointFormat.Native,
            public_bytes
        )

        # Populate private key scalar (convert bytes to integer)
        private_int = int.from_bytes(private_bytes, byteorder='big')
        pk.keymaterial.s = MPI(private_int)

        # Compute checksum
        pk.keymaterial._compute_chksum()

    @classmethod
    def generate_pgp_key(
        cls,
        seed_phrase: str | bytes,
        key_type: Literal["rsa", "ed25519", "ecdsa"],
        key_param: int | str,
        user_id: str,
        purpose: Literal["certify", "sign", "encrypt", "authenticate"],
        context: str = "pgp/primary",
        expires_days: Optional[int] = None,
        created_timestamp: Optional[datetime] = None
    ) -> tuple[pgpy.PGPKey, Dict]:
        """
        Generate a PGP key using deterministic key generation.

        Args:
            seed_phrase: Seed phrase or bytes for deterministic generation
            key_type: Key type (rsa, ed25519, ecdsa)
            key_param: For RSA: key size (2048, 4096). For ECDSA: curve name (secp256r1, etc.)
            user_id: User ID string (e.g., "Name <email@example.com>")
            purpose: Key purpose (certify, sign, encrypt, authenticate)
            context: Derivation context string
            expires_days: Optional expiration in days from now
            created_timestamp: Key creation timestamp (default: 2020-01-01 00:00:00 UTC for determinism)

        Returns:
            Tuple of (PGPKey object, info dict)
        """
        # Use fixed timestamp for deterministic generation if not specified
        if created_timestamp is None:
            created_timestamp = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Generate underlying cryptography key
        if key_type == "rsa":
            crypto_key = AsymmetricKeyGenerator.generate_rsa_key(
                seed_phrase=seed_phrase,
                key_size=int(key_param),
                context=context
            )
        elif key_type == "ed25519":
            crypto_key = AsymmetricKeyGenerator.generate_ed25519_key(
                seed_phrase=seed_phrase,
                context=context
            )
        elif key_type == "ecdsa":
            crypto_key = AsymmetricKeyGenerator.generate_ec_key(
                seed_phrase=seed_phrase,
                curve_name=str(key_param),
                context=context
            )
        else:
            raise ValueError(f"Unsupported key type: {key_type}")

        # Determine key flags based on purpose
        key_flags = cls._get_key_flags(purpose)

        # Create PGP key using pgpy
        pgp_key = cls._create_pgp_key_from_crypto(
            crypto_key,
            key_type,
            key_param,
            user_id,
            key_flags,
            expires_days,
            created_timestamp
        )

        # Extract key information
        info = {
            "fingerprint": str(pgp_key.fingerprint),
            "key_id": str(pgp_key.fingerprint)[-16:],
            "key_type": key_type,
            "key_size": str(key_param),
            "created": int(pgp_key.created.timestamp()),
            "expires": int(pgp_key.expires_at.timestamp()) if pgp_key.expires_at else None,
            "usage_flags": [f.name for f in key_flags],
        }

        return pgp_key, info

    @staticmethod
    def _get_key_flags(purpose: str) -> List[KeyFlags]:
        """Get key usage flags based on purpose."""
        flags_map = {
            "certify": [KeyFlags.Certify],
            "sign": [KeyFlags.Sign],
            "encrypt": [KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage],
            "authenticate": [KeyFlags.Authentication],
        }
        return flags_map.get(purpose, [])

    @classmethod
    def _create_pgp_key_from_crypto(
        cls,
        crypto_key,
        key_type: str,
        key_param: int | str,
        user_id: str,
        key_flags: List[KeyFlags],
        expires_days: Optional[int],
        created_timestamp: datetime
    ) -> pgpy.PGPKey:
        """
        Create a PGPKey from a cryptography key object with deterministic properties.

        This method manually constructs PGP key packets to ensure deterministic generation,
        using the provided cryptography key material and timestamp.
        """
        # Create empty PrivKeyV4 packet
        pk = PrivKeyV4()
        pk.created = created_timestamp

        # Set algorithm and populate key material based on key type
        if key_type == "rsa":
            pk.pkalg = PubKeyAlgorithm.RSAEncryptOrSign
            cls._populate_rsa_key_material(crypto_key, pk)

        elif key_type == "ed25519":
            pk.pkalg = PubKeyAlgorithm.EdDSA
            cls._populate_ed25519_key_material(crypto_key, pk)

        elif key_type == "ecdsa":
            # Map curve names to pgpy curve OID constants
            curve_map = {
                "secp256r1": EllipticCurveOID.NIST_P256,
                "secp384r1": EllipticCurveOID.NIST_P384,
                "secp521r1": EllipticCurveOID.NIST_P521,
            }
            pk.pkalg = PubKeyAlgorithm.ECDSA
            curve_oid = curve_map.get(str(key_param), EllipticCurveOID.NIST_P256)
            cls._populate_ecdsa_key_material(crypto_key, pk, curve_oid)

        else:
            raise ValueError(f"Unsupported key type: {key_type}")

        # Update packet header length
        pk.update_hlen()

        # Wrap in PGPKey
        pgp_key = pgpy.PGPKey()
        pgp_key._key = pk

        # Add user ID with preferences
        uid = pgpy.PGPUID.new(user_id)
        pgp_key.add_uid(
            uid,
            usage=key_flags,
            hashes=[HashAlgorithm.SHA256, HashAlgorithm.SHA384, HashAlgorithm.SHA512],
            ciphers=[
                SymmetricKeyAlgorithm.AES256,
                SymmetricKeyAlgorithm.AES192,
                SymmetricKeyAlgorithm.AES128
            ],
            compression=[
                CompressionAlgorithm.ZLIB,
                CompressionAlgorithm.BZ2,
                CompressionAlgorithm.ZIP
            ],
            key_expiration=timedelta(days=expires_days) if expires_days else None
        )

        return pgp_key


# ============================================================================
# Command: PGP Identity
# ============================================================================

@cli.command(name='derive-pgp-identity')
@click.option('--name', '-n', required=True, help='Full name for PGP identity')
@click.option('--email', '-e', required=True, help='Email address for PGP identity')
@click.option('--seed', '-s', default=None, help='Optional seed phrase for deterministic generation (stdin: -, file: @path, fd: fd:N, env: env:NAME)')
@click.option('--key-spec', '-k', default='ed25519',
              help='Key specification: ed25519 | rsa[:2048|4096] | ecdsa[:secp256r1|secp384r1|secp521r1] (default: ed25519)')
@click.option('--with-subkeys', '-w', is_flag=True, help='Generate subkeys for signing, encryption, and authentication')
@click.option('--expires-days', '-x', type=int, default=None, help='Key expiration in days from creation (default: no expiration)')
@click.option('--created-date', type=str, default=None, help='Creation date (ISO8601 or Unix epoch). Default: 2020-01-01 for deterministic, current time for random')
@click.option('--expires-date', type=str, default=None, help='Expiration date (ISO8601 or Unix epoch). Overrides --expires-days')
@click.option('--pretty', '-p', is_flag=True, help='Pretty print JSON output')
def derive_pgp_identity(
    name: str,
    email: str,
    seed: Optional[str],
    key_spec: str,
    with_subkeys: bool,
    expires_days: Optional[int],
    created_date: Optional[str],
    expires_date: Optional[str],
    pretty: bool
):
    """
    Generate a PGP identity with optional deterministic derivation.

    This command generates a complete PGP identity including a primary key
    (for certification) and optional subkeys for signing, encryption, and
    authentication.

    Without --seed: Generates random keys (non-deterministic)
    With --seed: Generates deterministic keys from seed phrase

    Examples:

        # Generate random Ed25519 identity with subkeys
        degen-crypto derive-pgp-identity -n "Alice" -e "alice@example.com" -w

        # Generate deterministic Ed25519 identity from seed
        degen-crypto derive-pgp-identity -n "Alice" -e "alice@example.com" -s @seed.txt -w

        # Generate RSA-4096 identity
        degen-crypto derive-pgp-identity -n "John Doe" -e "john@example.com" -k rsa -s @seed.txt -w

        # Generate RSA-2048 identity
        degen-crypto derive-pgp-identity -n "John Doe" -e "john@example.com" -k rsa:2048 -s @seed.txt

        # Generate ECDSA identity with P-384 curve
        degen-crypto derive-pgp-identity -n "Bob" -e "bob@example.com" -k ecdsa:secp384r1 -s @seed.txt -w
    """
    # Load seed phrase (optional)
    seed_phrase = None if seed is None else InputLoader.load_text(seed)
    deterministic = seed_phrase is not None

    # Calculate seed entropy (only if seed provided)
    seed_entropy = None
    if seed_phrase:
        entropy_metrics_dict = EntropyAnalyzer.calculate_entropy_metrics(seed_phrase)
        seed_entropy = EntropyMetrics(**entropy_metrics_dict)

    # Construct user ID
    user_id = f"{name} <{email}>"

    # Parse key specification
    try:
        key_type, key_param, key_param_str = PGPIdentityGenerator.parse_key_spec(key_spec)
    except click.BadParameter as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    # Parse creation timestamp
    created_timestamp = None
    if created_date:
        try:
            created_timestamp = parse_timestamp(created_date)
        except ValueError as e:
            click.echo(f"Error parsing --created-date: {e}", err=True)
            raise SystemExit(1)
    elif not deterministic:
        # For random generation, use current time (not fixed timestamp)
        created_timestamp = datetime.now(timezone.utc)
    # Otherwise default is handled in generate_pgp_key (2020-01-01 for deterministic)

    # Calculate expiration days
    final_expires_days = expires_days
    if expires_date:
        # Parse expiration date
        try:
            expires_timestamp = parse_timestamp(expires_date)
        except ValueError as e:
            click.echo(f"Error parsing --expires-date: {e}", err=True)
            raise SystemExit(1)
        # Calculate creation timestamp for calculation
        if created_timestamp is None:
            created_timestamp = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Calculate days between creation and expiration
        delta = expires_timestamp - created_timestamp
        final_expires_days = delta.days
        if final_expires_days < 0:
            click.echo("Error: Expiration date must be after creation date", err=True)
            raise click.Abort()

    # Generate primary key (certify + sign)
    primary_context = f"pgp/{email}/primary"
    primary_pgp_key, primary_info = PGPIdentityGenerator.generate_pgp_key(
        seed_phrase=seed_phrase,
        key_type=key_type,
        key_param=key_param,
        user_id=user_id,
        purpose="certify",
        context=primary_context,
        expires_days=final_expires_days,
        created_timestamp=created_timestamp
    )

    # Create primary key info
    primary_key_info = PGPKeyInfo(
        fingerprint=primary_info["fingerprint"],
        key_id=primary_info["key_id"],
        key_type=key_type,
        key_size=key_param_str,
        created=primary_info["created"],
        expires=primary_info["expires"],
        usage_flags=primary_info["usage_flags"],
        public_key_armored=str(primary_pgp_key.pubkey),
        private_key_armored=str(primary_pgp_key)
    )

    # Generate subkeys if requested
    subkeys_info = []
    if with_subkeys:
        # Signing subkey
        signing_pgp_key, signing_info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type=key_type,
            key_param=key_param,
            user_id=user_id,
            purpose="sign",
            context=f"pgp/{email}/signing",
            expires_days=final_expires_days,
            created_timestamp=created_timestamp
        )
        subkeys_info.append(PGPSubkeyInfo(
            fingerprint=signing_info["fingerprint"],
            key_id=signing_info["key_id"],
            key_type=key_type,
            purpose="signing",
            usage_flags=signing_info["usage_flags"]
        ))

        # Encryption subkey
        encrypt_pgp_key, encrypt_info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type=key_type,
            key_param=key_param,
            user_id=user_id,
            purpose="encrypt",
            context=f"pgp/{email}/encryption",
            expires_days=final_expires_days,
            created_timestamp=created_timestamp
        )
        subkeys_info.append(PGPSubkeyInfo(
            fingerprint=encrypt_info["fingerprint"],
            key_id=encrypt_info["key_id"],
            key_type=key_type,
            purpose="encryption",
            usage_flags=encrypt_info["usage_flags"]
        ))

        # Authentication subkey
        auth_pgp_key, auth_info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type=key_type,
            key_param=key_param,
            user_id=user_id,
            purpose="authenticate",
            context=f"pgp/{email}/authentication",
            expires_days=final_expires_days,
            created_timestamp=created_timestamp
        )
        subkeys_info.append(PGPSubkeyInfo(
            fingerprint=auth_info["fingerprint"],
            key_id=auth_info["key_id"],
            key_type=key_type,
            purpose="authentication",
            usage_flags=auth_info["usage_flags"]
        ))

    # Create metadata
    metadata = PGPIdentityMetadata(
        derivation_method="PBKDF2-HMAC-SHA512" if deterministic else "Random",
        iterations=2048 if deterministic else 0,
        deterministic=deterministic,
        seed_entropy=seed_entropy
    )

    # Create output
    output = PGPIdentityOutput(
        user_id=user_id,
        primary_key=primary_key_info,
        subkeys=subkeys_info if subkeys_info else None,
        public_key_bundle=str(primary_pgp_key.pubkey),
        private_key_bundle=str(primary_pgp_key),
        metadata=metadata
    )

    click.echo(output.model_dump_json(indent=2 if pretty else None))


# ============================================================================
# Command: PGP Key
# ============================================================================

@cli.command(name='derive-pgp-key')
@click.option('--identity', '-i', required=True, help='Identity string (email or name)')
@click.option('--seed', '-s', default=None, help='Optional seed phrase for deterministic generation (stdin: -, file: @path, fd: fd:N, env: env:NAME)')
@click.option('--key-spec', '-k', default='ed25519',
              help='Key specification: ed25519 | rsa[:2048|4096] | ecdsa[:secp256r1|secp384r1|secp521r1] (default: ed25519)')
@click.option('--purpose', '-u',
              type=click.Choice(['certify', 'sign', 'encrypt', 'authenticate']),
              default='sign',
              help='Key purpose/usage')
@click.option('--expires-days', '-x', type=int, default=None, help='Key expiration in days from creation')
@click.option('--created-date', type=str, default=None, help='Creation date (ISO8601 or Unix epoch). Default: 2020-01-01 for deterministic, current time for random')
@click.option('--expires-date', type=str, default=None, help='Expiration date (ISO8601 or Unix epoch). Overrides --expires-days')
@click.option('--pretty', '-p', is_flag=True, help='Pretty print JSON output')
def derive_pgp_key(
    identity: str,
    seed: Optional[str],
    key_spec: str,
    purpose: str,
    expires_days: Optional[int],
    created_date: Optional[str],
    expires_date: Optional[str],
    pretty: bool
):
    """
    Generate a single PGP key with optional deterministic derivation.

    This command generates a single PGP key for a specific purpose.
    Useful for generating individual keys or testing.

    Without --seed: Generates random keys (non-deterministic)
    With --seed: Generates deterministic keys from seed phrase

    Examples:

        # Generate random Ed25519 signing key
        degen-crypto derive-pgp-key -i "alice@example.com" -u sign

        # Generate deterministic Ed25519 signing key
        degen-crypto derive-pgp-key -i "alice@example.com" -s @seed.txt -u sign

        # Generate RSA-4096 encryption key
        degen-crypto derive-pgp-key -i "bob@example.com" -s @seed.txt -k rsa -u encrypt

        # Generate RSA-2048 key
        degen-crypto derive-pgp-key -i "bob@example.com" -s @seed.txt -k rsa:2048 -u sign

        # Generate ECDSA P-384 key
        degen-crypto derive-pgp-key -i "carol@example.com" -s @seed.txt -k ecdsa:secp384r1 -u sign
    """
    # Load seed phrase (optional)
    seed_phrase = None if seed is None else InputLoader.load_text(seed)
    deterministic = seed_phrase is not None

    # Calculate seed entropy (only if seed provided)
    seed_entropy = None
    if seed_phrase:
        entropy_metrics_dict = EntropyAnalyzer.calculate_entropy_metrics(seed_phrase)
        seed_entropy = EntropyMetrics(**entropy_metrics_dict)

    # Parse key specification
    try:
        key_type, key_param, key_param_str = PGPIdentityGenerator.parse_key_spec(key_spec)
    except click.BadParameter as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    # Parse creation timestamp
    created_timestamp = None
    if created_date:
        try:
            created_timestamp = parse_timestamp(created_date)
        except ValueError as e:
            click.echo(f"Error parsing --created-date: {e}", err=True)
            raise SystemExit(1)
    elif not deterministic:
        # For random generation, use current time (not fixed timestamp)
        created_timestamp = datetime.now(timezone.utc)
    # Otherwise default is handled in generate_pgp_key (2020-01-01 for deterministic)

    # Calculate expiration days
    final_expires_days = expires_days
    if expires_date:
        # Parse expiration date
        try:
            expires_timestamp = parse_timestamp(expires_date)
        except ValueError as e:
            click.echo(f"Error parsing --expires-date: {e}", err=True)
            raise SystemExit(1)
        # Calculate creation timestamp for calculation
        if created_timestamp is None:
            created_timestamp = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Calculate days between creation and expiration
        delta = expires_timestamp - created_timestamp
        final_expires_days = delta.days
        if final_expires_days < 0:
            click.echo("Error: Expiration date must be after creation date", err=True)
            raise click.Abort()

    # Generate key
    context = f"pgp/{identity}/{purpose}"
    user_id = identity

    pgp_key, info = PGPIdentityGenerator.generate_pgp_key(
        seed_phrase=seed_phrase,
        key_type=key_type,
        key_param=key_param,
        user_id=user_id,
        purpose=purpose,
        context=context,
        expires_days=final_expires_days,
        created_timestamp=created_timestamp
    )

    # Create key info
    key_info = PGPKeyInfo(
        fingerprint=info["fingerprint"],
        key_id=info["key_id"],
        key_type=key_type,
        key_size=key_param_str,
        created=info["created"],
        expires=info["expires"],
        usage_flags=info["usage_flags"],
        public_key_armored=str(pgp_key.pubkey),
        private_key_armored=str(pgp_key)
    )

    # Create metadata
    metadata = PGPIdentityMetadata(
        derivation_method="PBKDF2-HMAC-SHA512" if deterministic else "Random",
        iterations=2048 if deterministic else 0,
        deterministic=deterministic,
        seed_entropy=seed_entropy
    )

    # Create output
    output = PGPKeyOutput(
        key_info=key_info,
        metadata=metadata
    )

    click.echo(output.model_dump_json(indent=2 if pretty else None))
