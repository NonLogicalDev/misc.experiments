"""
Test suite for PGP identity generation functionality.

Tests cover:
- PGP key generation (RSA, Ed25519, ECDSA)
- Deterministic key derivation
- Key flags and purposes
- PGP identity generation with subkeys
- CLI commands
"""

# Standard library imports
import json

# Third-party imports
from click.testing import CliRunner

# Local imports
from degen_crypto.tool_pgp import (
    PGPIdentityGenerator,
    PGPKeyInfo,
    PGPSubkeyInfo,
    PGPIdentityMetadata,
    PGPIdentityOutput,
    PGPKeyOutput,
    derive_pgp_identity,
    derive_pgp_key,
)
from degen_crypto.lib_common import EntropyMetrics


class TestPGPIdentityGenerator:
    """Test suite for PGPIdentityGenerator class."""

    def test_get_key_flags_certify(self):
        """Test key flags for certify purpose."""
        flags = PGPIdentityGenerator._get_key_flags("certify")
        assert len(flags) == 1
        assert flags[0].name == "Certify"

    def test_get_key_flags_sign(self):
        """Test key flags for sign purpose."""
        flags = PGPIdentityGenerator._get_key_flags("sign")
        assert len(flags) == 1
        assert flags[0].name == "Sign"

    def test_get_key_flags_encrypt(self):
        """Test key flags for encrypt purpose."""
        flags = PGPIdentityGenerator._get_key_flags("encrypt")
        assert len(flags) == 2
        flag_names = [f.name for f in flags]
        assert "EncryptCommunications" in flag_names
        assert "EncryptStorage" in flag_names

    def test_get_key_flags_authenticate(self):
        """Test key flags for authenticate purpose."""
        flags = PGPIdentityGenerator._get_key_flags("authenticate")
        assert len(flags) == 1
        assert flags[0].name == "Authentication"

    def test_generate_pgp_key_ed25519(self):
        """Test generating Ed25519 PGP key."""
        seed_phrase = "test-seed-phrase"
        user_id = "Test User <test@example.com>"
        context = "pgp/test"

        pgp_key, info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="sign",
            context=context,
            expires_days=None
        )

        assert pgp_key is not None
        assert info["key_type"] == "ed25519"
        assert "fingerprint" in info
        assert "key_id" in info
        assert len(info["fingerprint"]) == 40  # Full fingerprint is 40 hex chars
        assert len(info["key_id"]) == 16  # Short key ID is 16 hex chars
        assert info["created"] > 0
        assert "usage_flags" in info

    def test_generate_pgp_key_rsa(self):
        """Test generating RSA PGP key."""
        seed_phrase = "test-seed-phrase"
        user_id = "Test User <test@example.com>"
        context = "pgp/test"

        pgp_key, info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="rsa",
            key_param=2048,
            user_id=user_id,
            purpose="sign",
            context=context,
            expires_days=None
        )

        assert pgp_key is not None
        assert info["key_type"] == "rsa"
        assert info["key_size"] == "2048"
        assert "fingerprint" in info
        assert "key_id" in info

    def test_generate_pgp_key_ecdsa(self):
        """Test generating ECDSA PGP key."""
        seed_phrase = "test-seed-phrase"
        user_id = "Test User <test@example.com>"
        context = "pgp/test"

        pgp_key, info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ecdsa",
            key_param="secp256r1",
            user_id=user_id,
            purpose="sign",
            context=context,
            expires_days=None
        )

        assert pgp_key is not None
        assert info["key_type"] == "ecdsa"
        assert info["key_size"] == "secp256r1"
        assert "fingerprint" in info
        assert "key_id" in info

    def test_generate_pgp_key_deterministic(self):
        """Test that same seed produces same PGP key."""
        seed_phrase = "deterministic-test-seed"
        user_id = "Test User <test@example.com>"
        context = "pgp/deterministic"

        pgp_key1, info1 = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="sign",
            context=context,
            expires_days=None
        )

        pgp_key2, info2 = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="sign",
            context=context,
            expires_days=None
        )

        # Fingerprints should match (deterministic)
        assert info1["fingerprint"] == info2["fingerprint"]
        assert info1["key_id"] == info2["key_id"]

    def test_generate_pgp_key_different_contexts(self):
        """Test that different contexts produce different keys."""
        seed_phrase = "test-seed"
        user_id = "Test User <test@example.com>"

        pgp_key1, info1 = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="sign",
            context="pgp/context1",
            expires_days=None
        )

        pgp_key2, info2 = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="sign",
            context="pgp/context2",
            expires_days=None
        )

        # Should produce different fingerprints
        assert info1["fingerprint"] != info2["fingerprint"]

    def test_generate_pgp_key_different_purposes(self):
        """Test that different purposes have different flags."""
        seed_phrase = "test-seed"
        user_id = "Test User <test@example.com>"
        context = "pgp/test"

        cert_key, cert_info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="certify",
            context=context,
            expires_days=None
        )

        sign_key, sign_info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="sign",
            context=context,
            expires_days=None
        )

        # Should have different usage flags
        assert "Certify" in cert_info["usage_flags"]
        assert "Sign" in sign_info["usage_flags"]

    def test_generate_pgp_key_with_expiration(self):
        """Test PGP key generation with expiration."""
        seed_phrase = "test-seed"
        user_id = "Test User <test@example.com>"
        context = "pgp/test"

        pgp_key, info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="sign",
            context=context,
            expires_days=365
        )

        assert info["expires"] is not None
        assert info["expires"] > info["created"]

    def test_generate_pgp_key_without_expiration(self):
        """Test PGP key generation without expiration."""
        seed_phrase = "test-seed"
        user_id = "Test User <test@example.com>"
        context = "pgp/test"

        pgp_key, info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="sign",
            context=context,
            expires_days=None
        )

        assert info["expires"] is None

    def test_generate_pgp_key_unsupported_type(self):
        """Test that unsupported key types raise ValueError."""
        seed_phrase = "test-seed"
        user_id = "Test User <test@example.com>"

        try:
            PGPIdentityGenerator.generate_pgp_key(
                seed_phrase=seed_phrase,
                key_type="unsupported",
                key_param=None,
                user_id=user_id,
                purpose="sign",
                context="pgp/test",
                expires_days=None
            )
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Unsupported key type" in str(e)


class TestPGPModels:
    """Test suite for PGP Pydantic models."""

    def test_pgp_key_info(self):
        """Test PGPKeyInfo model."""
        key_info = PGPKeyInfo(
            fingerprint="ABCD1234EFGH5678IJKL9012MNOP3456QRST7890",
            key_id="QRST7890",
            key_type="ed25519",
            key_size="Curve25519",
            created=1000000000,
            expires=None,
            usage_flags=["Sign"],
            public_key_armored="-----BEGIN PGP PUBLIC KEY BLOCK-----",
            private_key_armored="-----BEGIN PGP PRIVATE KEY BLOCK-----"
        )

        assert key_info.fingerprint == "ABCD1234EFGH5678IJKL9012MNOP3456QRST7890"
        assert key_info.key_id == "QRST7890"
        assert key_info.key_type == "ed25519"
        assert key_info.expires is None

    def test_pgp_subkey_info(self):
        """Test PGPSubkeyInfo model."""
        subkey_info = PGPSubkeyInfo(
            fingerprint="ABCD1234EFGH5678IJKL9012MNOP3456QRST7890",
            key_id="QRST7890",
            key_type="ed25519",
            purpose="signing",
            usage_flags=["Sign"]
        )

        assert subkey_info.purpose == "signing"
        assert "Sign" in subkey_info.usage_flags

    def test_pgp_identity_metadata(self):
        """Test PGPIdentityMetadata model."""
        entropy_metrics = EntropyMetrics(
            length=20,
            shannon_entropy_bits=3.5,
            min_entropy_bits=2.8,
            relative_entropy=0.7,
            estimated_strength_bits=70.0,
            quality="good"
        )

        metadata = PGPIdentityMetadata(
            derivation_method="PBKDF2-HMAC-SHA512",
            iterations=2048,
            deterministic=True,
            seed_entropy=entropy_metrics
        )

        assert metadata.derivation_method == "PBKDF2-HMAC-SHA512"
        assert metadata.iterations == 2048
        assert metadata.deterministic is True
        assert metadata.seed_entropy is not None


class TestDerivePGPIdentityCommand:
    """Test suite for derive-pgp-identity CLI command."""

    def test_derive_pgp_identity_missing_seed(self):
        """Test that missing seed raises error."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_identity, [
            "--name", "Test User",
            "--email", "test@example.com"
        ])

        assert result.exit_code != 0
        assert "seed is required" in result.output.lower()

    def test_derive_pgp_identity_basic(self):
        """Test basic PGP identity generation."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_identity, [
            "--name", "Test User",
            "--email", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "ed25519"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert "user_id" in output
        assert "primary_key" in output
        assert "metadata" in output
        assert output["user_id"] == "Test User <test@example.com>"
        assert output["primary_key"]["key_type"] == "ed25519"
        assert "fingerprint" in output["primary_key"]
        assert "public_key_armored" in output["primary_key"]

    def test_derive_pgp_identity_with_subkeys(self):
        """Test PGP identity generation with subkeys."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_identity, [
            "--name", "Test User",
            "--email", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "ed25519",
            "--with-subkeys"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert "subkeys" in output
        assert output["subkeys"] is not None
        assert len(output["subkeys"]) == 3

        # Check subkey purposes
        purposes = [subkey["purpose"] for subkey in output["subkeys"]]
        assert "signing" in purposes
        assert "encryption" in purposes
        assert "authentication" in purposes

    def test_derive_pgp_identity_rsa(self):
        """Test RSA PGP identity generation."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_identity, [
            "--name", "Test User",
            "--email", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "rsa",
            "--key-size", "4096"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert output["primary_key"]["key_type"] == "rsa"
        assert "4096" in output["primary_key"]["key_size"]

    def test_derive_pgp_identity_ecdsa(self):
        """Test ECDSA PGP identity generation."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_identity, [
            "--name", "Test User",
            "--email", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "ecdsa",
            "--curve", "secp256r1"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert output["primary_key"]["key_type"] == "ecdsa"
        assert "secp256r1" in output["primary_key"]["key_size"]

    def test_derive_pgp_identity_with_expiration(self):
        """Test PGP identity with expiration."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_identity, [
            "--name", "Test User",
            "--email", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "ed25519",
            "--expires-days", "365"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert output["primary_key"]["expires"] is not None
        assert output["primary_key"]["expires"] > output["primary_key"]["created"]

    def test_derive_pgp_identity_pretty_output(self):
        """Test pretty JSON output."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_identity, [
            "--name", "Test User",
            "--email", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "ed25519",
            "--pretty"
        ])

        assert result.exit_code == 0
        # Pretty output should have newlines and indentation
        assert "\n" in result.output
        assert "  " in result.output  # Indentation
        output = json.loads(result.output)
        assert "user_id" in output


class TestDerivePGPKeyCommand:
    """Test suite for derive-pgp-key CLI command."""

    def test_derive_pgp_key_missing_seed(self):
        """Test that missing seed raises error."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_key, [
            "--identity", "test@example.com"
        ])

        assert result.exit_code != 0
        assert "seed is required" in result.output.lower()

    def test_derive_pgp_key_basic(self):
        """Test basic PGP key generation."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_key, [
            "--identity", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "ed25519",
            "--purpose", "sign"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert "key_info" in output
        assert "metadata" in output
        assert output["key_info"]["key_type"] == "ed25519"
        assert "fingerprint" in output["key_info"]
        assert "public_key_armored" in output["key_info"]

    def test_derive_pgp_key_rsa(self):
        """Test RSA PGP key generation."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_key, [
            "--identity", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "rsa",
            "--key-size", "4096",
            "--purpose", "encrypt"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert output["key_info"]["key_type"] == "rsa"
        assert "4096" in output["key_info"]["key_size"]

    def test_derive_pgp_key_ecdsa(self):
        """Test ECDSA PGP key generation."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_key, [
            "--identity", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "ecdsa",
            "--curve", "secp384r1",
            "--purpose", "authenticate"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert output["key_info"]["key_type"] == "ecdsa"
        assert "secp384r1" in output["key_info"]["key_size"]

    def test_derive_pgp_key_different_purposes(self):
        """Test PGP key generation with different purposes."""
        runner = CliRunner()
        seed = "test-seed"

        for purpose in ["certify", "sign", "encrypt", "authenticate"]:
            result = runner.invoke(derive_pgp_key, [
                "--identity", "test@example.com",
                "--seed", seed,
                "--key-type", "ed25519",
                "--purpose", purpose
            ])

            assert result.exit_code == 0
            output = json.loads(result.output)
            # Map purpose names to actual flag names
            purpose_flag_map = {
                "certify": "Certify",
                "sign": "Sign",
                "encrypt": ["EncryptCommunications", "EncryptStorage"],
                "authenticate": "Authentication"
            }
            expected_flags = purpose_flag_map.get(purpose, purpose.capitalize())
            if isinstance(expected_flags, list):
                # For encrypt, check that at least one of the flags is present
                assert any(flag in output["key_info"]["usage_flags"] for flag in expected_flags)
            else:
                assert expected_flags in output["key_info"]["usage_flags"]

    def test_derive_pgp_key_with_expiration(self):
        """Test PGP key with expiration."""
        runner = CliRunner()
        result = runner.invoke(derive_pgp_key, [
            "--identity", "test@example.com",
            "--seed", "test-seed-phrase",
            "--key-type", "ed25519",
            "--purpose", "sign",
            "--expires-days", "180"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert output["key_info"]["expires"] is not None
        assert output["key_info"]["expires"] > output["key_info"]["created"]

    def test_derive_pgp_key_deterministic(self):
        """Test that same seed produces same key."""
        runner = CliRunner()
        seed = "deterministic-test-seed"

        result1 = runner.invoke(derive_pgp_key, [
            "--identity", "test@example.com",
            "--seed", seed,
            "--key-type", "ed25519",
            "--purpose", "sign"
        ])

        result2 = runner.invoke(derive_pgp_key, [
            "--identity", "test@example.com",
            "--seed", seed,
            "--key-type", "ed25519",
            "--purpose", "sign"
        ])

        assert result1.exit_code == 0
        assert result2.exit_code == 0

        output1 = json.loads(result1.output)
        output2 = json.loads(result2.output)

        # Fingerprints should match (deterministic)
        assert output1["key_info"]["fingerprint"] == output2["key_info"]["fingerprint"]


class TestIntegration:
    """Integration tests for PGP functionality."""

    def test_end_to_end_pgp_identity_workflow(self):
        """Test complete PGP identity generation workflow."""
        seed_phrase = "integration-test-seed"
        user_id = "Integration Test <integration@example.com>"
        context = "pgp/integration"

        # Generate primary key
        primary_key, primary_info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="certify",
            context=f"{context}/primary",
            expires_days=None
        )

        # Generate signing subkey
        signing_key, signing_info = PGPIdentityGenerator.generate_pgp_key(
            seed_phrase=seed_phrase,
            key_type="ed25519",
            key_param=None,
            user_id=user_id,
            purpose="sign",
            context=f"{context}/signing",
            expires_days=None
        )

        # Verify keys were generated
        assert primary_key is not None
        assert signing_key is not None
        assert primary_info["fingerprint"] != signing_info["fingerprint"]

        # Verify key flags
        assert "Certify" in primary_info["usage_flags"]
        assert "Sign" in signing_info["usage_flags"]

    def test_pgp_identity_output_model(self):
        """Test that PGP identity output can be serialized."""
        entropy_metrics = EntropyMetrics(
            length=15,
            shannon_entropy_bits=3.2,
            min_entropy_bits=2.5,
            relative_entropy=0.65,
            estimated_strength_bits=48.0,
            quality="good"
        )

        primary_key_info = PGPKeyInfo(
            fingerprint="ABCD1234EFGH5678IJKL9012MNOP3456QRST7890",
            key_id="QRST7890",
            key_type="ed25519",
            key_size="Curve25519",
            created=1000000000,
            expires=None,
            usage_flags=["Certify"],
            public_key_armored="-----BEGIN PGP PUBLIC KEY BLOCK-----",
            private_key_armored="-----BEGIN PGP PRIVATE KEY BLOCK-----"
        )

        metadata = PGPIdentityMetadata(
            derivation_method="PBKDF2-HMAC-SHA512",
            iterations=2048,
            deterministic=True,
            seed_entropy=entropy_metrics
        )

        output = PGPIdentityOutput(
            user_id="Test User <test@example.com>",
            primary_key=primary_key_info,
            subkeys=None,
            public_key_bundle="-----BEGIN PGP PUBLIC KEY BLOCK-----",
            private_key_bundle="-----BEGIN PGP PRIVATE KEY BLOCK-----",
            metadata=metadata
        )

        # Test serialization
        json_output = output.model_dump(by_alias=True)
        assert "user_id" in json_output
        assert "primary_key" in json_output
        assert "_metadata" in json_output
        assert json_output["_metadata"]["deterministic"] is True

