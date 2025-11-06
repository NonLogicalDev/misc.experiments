"""
Test suite for password hash generation functionality.

Tests cover:
- Deterministic salt generation
- Bcrypt encoding
- Crypt salt encoding
- Individual hash generation methods
- Full password hash generation
- Deterministic vs non-deterministic behavior
- Password input handling
"""

# Standard library imports
import hashlib

# Third-party imports
from click.testing import CliRunner

# Local imports
from degen_crypto.tool_passwd import (
    PasswordHashGenerator,
    PasswordHashOutput,
    PasswordMetadata,
    UseCaseInfo,
    derive_passwd_set,
)
from degen_crypto.lib_common import (
    EntropyMetrics,
    DerivationInfo,
)


class TestPasswordHashGenerator:
    """Test suite for PasswordHashGenerator class."""

    def test_generate_deterministic_salt_same_input(self):
        """Test that same input produces same salt."""
        seed = "test-seed-phrase"
        context = "bcrypt"

        salt1 = PasswordHashGenerator.generate_deterministic_salt(seed, context, 16)
        salt2 = PasswordHashGenerator.generate_deterministic_salt(seed, context, 16)

        assert salt1 == salt2
        assert len(salt1) == 16

    def test_generate_deterministic_salt_different_context(self):
        """Test that different contexts produce different salts."""
        seed = "test-seed-phrase"

        salt_bcrypt = PasswordHashGenerator.generate_deterministic_salt(seed, "bcrypt", 16)
        salt_sha512 = PasswordHashGenerator.generate_deterministic_salt(seed, "sha512_crypt", 16)

        assert salt_bcrypt != salt_sha512

    def test_generate_deterministic_salt_different_seed(self):
        """Test that different seeds produce different salts."""
        context = "bcrypt"

        salt1 = PasswordHashGenerator.generate_deterministic_salt("seed1", context, 16)
        salt2 = PasswordHashGenerator.generate_deterministic_salt("seed2", context, 16)

        assert salt1 != salt2

    def test_generate_deterministic_salt_custom_length(self):
        """Test salt generation with custom lengths."""
        seed = "test-seed-phrase"
        context = "test"

        for length in [8, 16, 24, 32]:
            salt = PasswordHashGenerator.generate_deterministic_salt(seed, context, length)
            assert len(salt) == length

    def test_encode_bcrypt_salt_length(self):
        """Test that bcrypt salt encoding produces 22 characters."""
        salt_bytes = b"0123456789ABCDEF"  # 16 bytes
        encoded = PasswordHashGenerator.encode_bcrypt_salt(salt_bytes)

        assert len(encoded) == 22
        assert all(c in "./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
                  for c in encoded)

    def test_encode_bcrypt_salt_deterministic(self):
        """Test that bcrypt encoding is deterministic."""
        salt_bytes = b"0123456789ABCDEF"

        encoded1 = PasswordHashGenerator.encode_bcrypt_salt(salt_bytes)
        encoded2 = PasswordHashGenerator.encode_bcrypt_salt(salt_bytes)

        assert encoded1 == encoded2

    def test_encode_crypt_salt_valid_characters(self):
        """Test that crypt salt only contains valid characters."""
        salt_bytes = hashlib.sha256(b"test").digest()
        encoded = PasswordHashGenerator.encode_crypt_salt(salt_bytes, 16)

        assert len(encoded) == 16
        # Should only contain [./0-9A-Za-z]
        assert all(c in "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                  for c in encoded)

    def test_generate_bcrypt_hash_deterministic(self):
        """Test that bcrypt with seed produces same hash."""
        password = "testpassword"
        seed = "test-seed"

        hash1 = PasswordHashGenerator.generate_bcrypt_hash(password, seed)
        hash2 = PasswordHashGenerator.generate_bcrypt_hash(password, seed)

        assert hash1 == hash2
        assert hash1.startswith("$2b$12$")

    def test_generate_bcrypt_hash_random(self):
        """Test that bcrypt without seed produces different hashes."""
        password = "testpassword"

        hash1 = PasswordHashGenerator.generate_bcrypt_hash(password)
        hash2 = PasswordHashGenerator.generate_bcrypt_hash(password)

        assert hash1 != hash2
        assert hash1.startswith("$2b$12$")

    def test_generate_apr_md5_hash_deterministic(self):
        """Test deterministic APR MD5 hash generation."""
        password = "testpassword"
        seed = "test-seed"

        hash1 = PasswordHashGenerator.generate_apr_md5_hash(password, seed)
        hash2 = PasswordHashGenerator.generate_apr_md5_hash(password, seed)

        assert hash1 == hash2
        assert hash1.startswith("$apr1$")

    def test_generate_sha256_crypt_hash_deterministic(self):
        """Test deterministic SHA-256 crypt hash generation."""
        password = "testpassword"
        seed = "test-seed"

        hash1 = PasswordHashGenerator.generate_sha256_crypt_hash(password, seed)
        hash2 = PasswordHashGenerator.generate_sha256_crypt_hash(password, seed)

        assert hash1 == hash2
        assert hash1.startswith("$5$")

    def test_generate_sha512_crypt_hash_deterministic(self):
        """Test deterministic SHA-512 crypt hash generation."""
        password = "testpassword"
        seed = "test-seed"

        hash1 = PasswordHashGenerator.generate_sha512_crypt_hash(password, seed)
        hash2 = PasswordHashGenerator.generate_sha512_crypt_hash(password, seed)

        assert hash1 == hash2
        assert hash1.startswith("$6$")

    def test_generate_md5_crypt_hash_deterministic(self):
        """Test deterministic MD5 crypt hash generation."""
        password = "testpassword"
        seed = "test-seed"

        hash1 = PasswordHashGenerator.generate_md5_crypt_hash(password, seed)
        hash2 = PasswordHashGenerator.generate_md5_crypt_hash(password, seed)

        assert hash1 == hash2
        assert hash1.startswith("$1$")

    def test_generate_sha1_hash(self):
        """Test SHA-1 hash generation."""
        password = "testpassword"

        hash_value = PasswordHashGenerator.generate_sha1_hash(password)

        assert hash_value.startswith("{SHA}")
        # Verify it's deterministic (SHA-1 doesn't use salt in this implementation)
        assert hash_value == PasswordHashGenerator.generate_sha1_hash(password)

    def test_generate_argon2_hash_deterministic(self):
        """Test deterministic Argon2 hash generation."""
        password = "testpassword"
        seed = "test-seed"

        hash1 = PasswordHashGenerator.generate_argon2_hash(password, seed)
        hash2 = PasswordHashGenerator.generate_argon2_hash(password, seed)

        assert hash1 == hash2
        assert hash1.startswith("$argon2id$")

    def test_generate_argon2_hash_random(self):
        """Test random Argon2 hash generation."""
        password = "testpassword"

        hash1 = PasswordHashGenerator.generate_argon2_hash(password)
        hash2 = PasswordHashGenerator.generate_argon2_hash(password)

        assert hash1 != hash2
        assert hash1.startswith("$argon2id$")

    def test_generate_md5_legacy_hash(self):
        """Test legacy MD5 hash generation."""
        password = "testpassword"

        hash_value = PasswordHashGenerator.generate_md5_legacy_hash(password)

        assert hash_value.startswith("{MD5}")
        # Should be deterministic (no salt)
        assert hash_value == PasswordHashGenerator.generate_md5_legacy_hash(password)

    def test_generate_all_hashes_structure(self):
        """Test that generate_all_hashes returns correct structure."""
        password = "testpassword"
        seed = "test-seed"

        result = PasswordHashGenerator.generate_all_hashes(password, seed)

        assert isinstance(result, PasswordHashOutput)
        assert result.hashes["bcrypt"].startswith("$2b$")
        assert result.hashes["apr_md5"].startswith("$apr1$")
        assert result.hashes["sha256_crypt"].startswith("$5$")
        assert result.hashes["sha512_crypt"].startswith("$6$")
        assert result.hashes["md5_crypt"].startswith("$1$")
        assert result.hashes["sha1"].startswith("{SHA}")
        assert result.hashes["argon2"].startswith("$argon2id$")
        assert result.hashes["md5_legacy"].startswith("{MD5}")

    def test_generate_all_hashes_deterministic(self):
        """Test that generate_all_hashes is deterministic with seed."""
        password = "testpassword"
        seed = "test-seed"

        result1 = PasswordHashGenerator.generate_all_hashes(password, seed)
        result2 = PasswordHashGenerator.generate_all_hashes(password, seed)

        assert result1.hashes["bcrypt"] == result2.hashes["bcrypt"]
        assert result1.hashes["apr_md5"] == result2.hashes["apr_md5"]
        assert result1.hashes["sha256_crypt"] == result2.hashes["sha256_crypt"]
        assert result1.hashes["sha512_crypt"] == result2.hashes["sha512_crypt"]
        assert result1.hashes["md5_crypt"] == result2.hashes["md5_crypt"]
        assert result1.hashes["argon2"] == result2.hashes["argon2"]

    def test_generate_all_hashes_metadata_deterministic(self):
        """Test metadata for deterministic hash generation."""
        password = "testpassword"
        seed = "test-seed"

        result = PasswordHashGenerator.generate_all_hashes(password, seed)

        assert result.metadata.deterministic is True
        assert result.metadata.seed_phrase_used == seed
        assert result.metadata.derivation is not None
        assert result.metadata.derivation.method == "PBKDF2-HMAC-SHA512"
        assert result.metadata.derivation.iterations == 2048
        assert result.metadata.seed_entropy is not None

    def test_generate_all_hashes_metadata_random(self):
        """Test metadata for random hash generation."""
        password = "testpassword"

        result = PasswordHashGenerator.generate_all_hashes(password)

        assert result.metadata.deterministic is False
        assert result.metadata.seed_phrase_used is None
        assert result.metadata.derivation is None
        assert result.metadata.seed_entropy is None

    def test_generate_all_hashes_different_passwords(self):
        """Test that different passwords produce different hashes."""
        seed = "test-seed"

        result1 = PasswordHashGenerator.generate_all_hashes("password1", seed)
        result2 = PasswordHashGenerator.generate_all_hashes("password2", seed)

        assert result1.hashes["bcrypt"] != result2.hashes["bcrypt"]
        assert result1.hashes["sha512_crypt"] != result2.hashes["sha512_crypt"]
        assert result1.hashes["sha1"] != result2.hashes["sha1"]


class TestPasswordModels:
    """Test suite for password-related Pydantic models."""

    def test_password_metadata_minimal(self):
        """Test PasswordMetadata with minimal fields."""
        metadata = PasswordMetadata(deterministic=False)

        assert metadata.deterministic is False
        assert metadata.note is None
        assert metadata.seed_phrase_used is None
        assert metadata.derivation is None
        assert metadata.seed_entropy is None

    def test_password_metadata_full(self):
        """Test PasswordMetadata with all fields."""
        derivation = DerivationInfo(
            method="PBKDF2-HMAC-SHA512",
            iterations=2048,
            salt_prefix="test"
        )
        entropy = EntropyMetrics(
            length=10,
            shannon_entropy_bits=3.0,
            min_entropy_bits=2.0,
            relative_entropy=0.5,
            estimated_strength_bits=30.0,
            quality="fair"
        )

        metadata = PasswordMetadata(
            deterministic=True,
            note="Test note",
            seed_phrase_used="test-seed",
            derivation=derivation,
            seed_entropy=entropy
        )

        assert metadata.deterministic is True
        assert metadata.note == "Test note"
        assert metadata.seed_phrase_used == "test-seed"
        assert metadata.derivation == derivation
        assert metadata.seed_entropy == entropy

    def test_password_hash_output_model(self):
        """Test PasswordHashOutput model validation."""
        metadata = PasswordMetadata(deterministic=False)

        output = PasswordHashOutput(
            hashes={
                "bcrypt": "$2b$12$test",
                "apr_md5": "$apr1$test",
                "sha256_crypt": "$5$test",
                "sha512_crypt": "$6$test",
                "md5_crypt": "$1$test",
                "sha1": "{SHA}test",
                "argon2": "$argon2id$test",
                "md5_legacy": "{MD5}test",
            },
            _metadata=metadata
        )

        assert output.hashes["bcrypt"] == "$2b$12$test"
        assert output.metadata == metadata

    def test_use_case_info_model(self):
        """Test UseCaseInfo model."""
        metadata = PasswordMetadata(deterministic=True)

        use_case = UseCaseInfo(
            use_case="traefik",
            recommended="bcrypt",
            format="username:hash",
            note="Test note",
            hashes={"bcrypt": "$2b$12$test"},
            _metadata=metadata
        )

        assert use_case.use_case == "traefik"
        assert use_case.recommended == "bcrypt"
        assert use_case.hashes == {"bcrypt": "$2b$12$test"}


class TestDerivePasswdSetCommand:
    """Test suite for derive-passwd-set CLI command."""

    def test_derive_passwd_set_basic(self):
        """Test basic password set derivation."""
        runner = CliRunner()
        result = runner.invoke(derive_passwd_set, input="testpassword\ntestpassword\n")

        assert result.exit_code == 0
        assert "bcrypt" in result.output
        assert "sha512_crypt" in result.output

    def test_derive_passwd_set_with_seed(self):
        """Test password derivation with seed phrase."""
        runner = CliRunner()
        result = runner.invoke(
            derive_passwd_set,
            ["--seed", "test-seed"],
            input="testpassword\ntestpassword\n"
        )

        assert result.exit_code == 0
        assert '"deterministic": true' in result.output

    def test_derive_passwd_set_pretty_output(self):
        """Test pretty-printed output."""
        runner = CliRunner()
        result = runner.invoke(
            derive_passwd_set,
            ["--pretty"],
            input="testpassword\ntestpassword\n"
        )

        assert result.exit_code == 0
        # Pretty print should have indentation
        assert "  " in result.output

    def test_derive_passwd_set_quiet_mode(self):
        """Test quiet mode output."""
        runner = CliRunner()
        result = runner.invoke(
            derive_passwd_set,
            ["--quiet"],
            input="testpassword\ntestpassword\n"
        )

        assert result.exit_code == 0
        assert '"deterministic": false' in result.output

    def test_derive_passwd_set_use_case_traefik(self):
        """Test use case filtering for Traefik."""
        runner = CliRunner()
        result = runner.invoke(
            derive_passwd_set,
            ["--use-case", "traefik"],
            input="testpassword\ntestpassword\n"
        )

        assert result.exit_code == 0
        assert '"use_case": "traefik"' in result.output
        assert "bcrypt" in result.output or "apr_md5" in result.output

    def test_derive_passwd_set_use_case_nixos(self):
        """Test use case filtering for NixOS."""
        runner = CliRunner()
        result = runner.invoke(
            derive_passwd_set,
            ["--use-case", "nixos"],
            input="testpassword\ntestpassword\n"
        )

        assert result.exit_code == 0
        assert '"use_case": "nixos"' in result.output
        assert "sha512_crypt" in result.output

    def test_derive_passwd_set_custom_username(self):
        """Test custom username (metadata only)."""
        runner = CliRunner()
        result = runner.invoke(
            derive_passwd_set,
            ["--username", "bob"],
            input="testpassword\ntestpassword\n"
        )

        assert result.exit_code == 0
        # Username is accepted but not in output (could be used for htpasswd format)

    def test_derive_passwd_set_stdin(self):
        """Test reading password from stdin."""
        runner = CliRunner()
        result = runner.invoke(
            derive_passwd_set,
            input="testpassword\n"
        )

        assert result.exit_code == 0
        assert "bcrypt" in result.output

    def test_derive_passwd_set_deterministic_same_output(self):
        """Test that same seed produces same output."""
        runner = CliRunner()

        result1 = runner.invoke(
            derive_passwd_set,
            ["--seed", "same-seed"],
            input="testpassword\ntestpassword\n"
        )
        result2 = runner.invoke(
            derive_passwd_set,
            ["--seed", "same-seed"],
            input="testpassword\ntestpassword\n"
        )

        assert result1.exit_code == 0
        assert result2.exit_code == 0
        assert result1.output == result2.output


class TestIntegration:
    """Integration tests for password functionality."""

    def test_end_to_end_deterministic_workflow(self):
        """Test complete deterministic password generation workflow."""
        password = "my-secure-password"
        seed = "my-infrastructure-seed"

        # Generate hashes
        hashes = PasswordHashGenerator.generate_all_hashes(password, seed)

        # Verify determinism
        hashes2 = PasswordHashGenerator.generate_all_hashes(password, seed)
        assert hashes.hashes["bcrypt"] == hashes2.hashes["bcrypt"]
        assert hashes.hashes["sha512_crypt"] == hashes2.hashes["sha512_crypt"]

        # Verify metadata
        assert hashes.metadata.deterministic is True
        assert hashes.metadata.seed_phrase_used == seed

        # Export to dict
        output = hashes.model_dump(by_alias=True)
        assert "_metadata" in output
        assert output["_metadata"]["deterministic"] is True

    def test_password_verification_bcrypt(self):
        """Test that generated bcrypt hash can verify password."""
        import bcrypt

        password = "testpassword"
        seed = "test-seed"

        hash_value = PasswordHashGenerator.generate_bcrypt_hash(password, seed)

        # Verify password
        assert bcrypt.checkpw(password.encode('utf-8'), hash_value.encode('utf-8'))
        # Verify wrong password fails
        assert not bcrypt.checkpw(b"wrongpassword", hash_value.encode('utf-8'))

    def test_all_hash_types_present(self):
        """Test that all expected hash types are generated."""
        hashes = PasswordHashGenerator.generate_all_hashes("test", "seed")

        expected_hashes = [
            'bcrypt', 'apr_md5', 'sha256_crypt', 'sha512_crypt',
            'md5_crypt', 'sha1', 'argon2', 'md5_legacy'
        ]

        for hash_type in expected_hashes:
            assert hash_type in hashes.hashes
            assert hashes.hashes[hash_type] is not None
            assert len(hashes.hashes[hash_type]) > 0
