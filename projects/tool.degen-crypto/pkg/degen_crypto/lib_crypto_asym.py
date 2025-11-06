"""
Common Asymmetric Key Generation Utilities.

This module provides deterministic asymmetric key generation functions
shared across multiple crypto tools (SSH, X.509, etc.).

Features:
- Deterministic Ed25519 key generation
- Deterministic RSA key generation (2048, 4096 bits)
- Deterministic ECDSA/EC key generation (P-256, P-384, P-521)
- Deterministic DSA key generation (legacy, 1024-3072 bits)
- SSH key pair generation (OpenSSH format)
- X.509 key pair generation (PEM format)
- Unified interface for key generation across different use cases
"""

# Standard library imports
import hashlib
import hmac

# Third-party imports
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519, dsa
from Crypto.PublicKey import RSA as CryptoRSA
from Crypto.PublicKey import DSA as CryptoDSA

# Local imports
from degen_crypto.lib_common import DeterministicRandom, SeedDerivation


# ============================================================================
# Asymmetric Key Generation
# ============================================================================

class AsymmetricKeyGenerator:
    """
    Deterministic asymmetric key generation utilities.

    Provides methods for generating Ed25519, RSA, EC, and DSA keys deterministically
    from a seed, ensuring the same seed always produces the same keys.
    """

    @staticmethod
    def _derive_seed_bytes(seed_input: bytes | str, context: str, dklen: int) -> bytes:
        """
        Normalize seed input to bytes, deriving from phrase when needed.

        Args:
            seed_input: Seed phrase (str) or raw seed bytes
            context: Context string used as salt phrase
            dklen: Desired key length in bytes

        Returns:
            Seed bytes of length dklen
        """
        if isinstance(seed_input, (bytes, bytearray, memoryview)):
            seed_bytes = bytes(seed_input)
            if len(seed_bytes) >= dklen:
                return seed_bytes[:dklen]
            return seed_bytes
        if isinstance(seed_input, str):
            return SeedDerivation.derive_master_seed(
                seed_phrase=seed_input,
                salt_phrase=context,
                dklen=dklen
            )
        raise TypeError("seed_input must be bytes-like or a seed phrase string.")

    @classmethod
    def generate_ed25519_key(
        cls,
        seed_phrase: bytes | str | None = None,
        context: str = "asym/ed25519"
    ) -> ed25519.Ed25519PrivateKey:
        """
        Generate an Ed25519 private key.

        When a seed phrase (or raw seed bytes) is provided, the key generation
        is deterministic. Otherwise, a fresh random key is produced.

        Args:
            seed_phrase: Seed phrase or raw seed bytes for deterministic generation
            context: Context string used for phrase-based derivation

        Returns:
            Ed25519 private key (cryptography library format)
        """
        if seed_phrase is None:
            return ed25519.Ed25519PrivateKey.generate()

        seed_bytes = cls._derive_seed_bytes(seed_phrase, context, dklen=32)
        return ed25519.Ed25519PrivateKey.from_private_bytes(seed_bytes)

    @classmethod
    def generate_rsa_key(
        cls,
        seed_phrase: bytes | str | None = None,
        key_size: int = 4096,
        context: str | None = None
    ) -> rsa.RSAPrivateKey:
        """
        Generate an RSA private key.

        When a seed phrase (or raw seed bytes) is provided, the key generation
        is deterministic. Otherwise, a fresh random key is produced using the
        cryptography backend.

        Args:
            seed_phrase: Seed phrase or raw seed bytes for deterministic generation
            key_size: RSA key size in bits (2048, 4096, etc.)
            context: Optional context string overriding the default

        Returns:
            RSA private key (cryptography library format)
        """
        if seed_phrase is None:
            return rsa.generate_private_key(
                public_exponent=65537,
                key_size=key_size,
                backend=default_backend()
            )

        derivation_context = context or f"asym/rsa/{key_size}"
        seed_bytes = cls._derive_seed_bytes(seed_phrase, derivation_context, dklen=64)
        det_random = DeterministicRandom(seed_bytes)

        pycrypto_key = CryptoRSA.generate(key_size, randfunc=det_random)
        pem_key = pycrypto_key.export_key('PEM')

        return serialization.load_pem_private_key(
            pem_key,
            password=None,
            backend=default_backend()
        )

    @classmethod
    def generate_ec_key(
        cls,
        seed_phrase: bytes | str | None,
        curve_name: str = "secp256r1",
        context: str | None = None
    ) -> ec.EllipticCurvePrivateKey:
        """
        Generate an EC (elliptic curve) private key.

        Args:
            seed_phrase: Seed phrase or raw seed bytes for deterministic generation
            curve_name: Curve name (secp256r1, secp384r1, secp521r1)
            context: Optional context string overriding the default

        Returns:
            EC private key (cryptography library format)

        Raises:
            ValueError: If curve name is not supported
        """
        # Map curve names to cryptography curves
        curve_map = {
            "secp256r1": ec.SECP256R1(),
            "secp384r1": ec.SECP384R1(),
            "secp521r1": ec.SECP521R1(),
        }

        if curve_name not in curve_map:
            raise ValueError(f"Unsupported EC curve: {curve_name}")

        curve = curve_map[curve_name]

        if seed_phrase is None:
            return ec.generate_private_key(curve, default_backend())

        # EC key generation from seed
        # We derive a private scalar from the seed
        # Use HMAC to derive the private key value from seed
        derivation_context = context or f"asym/ec/{curve_name}"
        seed_bytes = cls._derive_seed_bytes(seed_phrase, derivation_context, dklen=64)
        private_value_bytes = hmac.new(seed_bytes, b"ec-private-key", hashlib.sha256).digest()
        private_value = int.from_bytes(private_value_bytes, byteorder='big')

        # Derive the EC private key from the integer value
        private_key = ec.derive_private_key(private_value, curve, default_backend())

        return private_key

    @classmethod
    def generate_dsa_key(
        cls,
        seed_phrase: bytes | str | None = None,
        key_size: int = 2048,
        context: str | None = None
    ) -> dsa.DSAPrivateKey:
        """
        Generate a DSA (Digital Signature Algorithm) private key.

        Note: DSA is a legacy algorithm. Ed25519 or RSA is recommended for new applications.
        DSA is included for compatibility with older systems.

        When a seed phrase (or raw seed bytes) is provided, the key generation
        is deterministic. Otherwise, a fresh random key is produced.

        Args:
            seed_phrase: Seed phrase or raw seed bytes for deterministic generation
            key_size: DSA key size in bits (1024, 2048, 3072). Default 2048.
            context: Optional context string overriding the default

        Returns:
            DSA private key (cryptography library format)

        Raises:
            ValueError: If key_size is not valid (must be 1024, 2048, or 3072)
        """
        if key_size not in (1024, 2048, 3072):
            raise ValueError(f"DSA key size must be 1024, 2048, or 3072, got {key_size}")

        if seed_phrase is None:
            return dsa.generate_private_key(
                key_size=key_size,
                backend=default_backend()
            )

        derivation_context = context or f"asym/dsa/{key_size}"
        seed_bytes = cls._derive_seed_bytes(seed_phrase, derivation_context, dklen=64)
        det_random = DeterministicRandom(seed_bytes)

        # Use pycryptodome for deterministic generation
        pycrypto_key = CryptoDSA.generate(key_size, randfunc=det_random)
        pem_key = pycrypto_key.export_key('PEM')

        # Convert to cryptography library format
        return serialization.load_pem_private_key(
            pem_key,
            password=None,
            backend=default_backend()
        )

    @classmethod
    def generate_private_key(
        cls,
        seed: bytes | str | None,
        key_type: str,
        param: int | str | None = None
    ) -> ed25519.Ed25519PrivateKey | rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | dsa.DSAPrivateKey:
        """
        Generate a private key (deterministic when seed is provided).

        This is a convenience method that routes to the appropriate
        key generation function based on key type.

        Args:
            seed: Seed phrase string, seed bytes, or None for random generation
            key_type: 'ed25519', 'rsa', 'ec', or 'dsa'
            param: For Ed25519: None (ignored). For RSA/DSA: key size (2048, 4096, etc.). For EC: curve name (secp256r1, secp384r1, secp521r1)

        Returns:
            Private key object (Ed25519, RSA, EC, or DSA)

        Raises:
            ValueError: If key type is not supported
        """
        if key_type == "ed25519":
            return cls.generate_ed25519_key(seed)

        elif key_type == "rsa":
            key_size = int(param)
            return cls.generate_rsa_key(seed, key_size)

        elif key_type == "ec":
            curve_name = str(param)
            return cls.generate_ec_key(seed, curve_name)

        elif key_type == "dsa":
            key_size = int(param) if param else 2048
            return cls.generate_dsa_key(seed, key_size)

        else:
            raise ValueError(f"Unsupported key type: {key_type}")
