"""
Test suite for SSH key and certificate generation functionality.

Tests cover:
- SSH key generation (Ed25519, RSA, ECDSA)
- Deterministic key derivation
- SSH certificate generation
- CLI commands
"""

# Standard library imports
import json

# Third-party imports
from click.testing import CliRunner

# Local imports
from degen_crypto.tool_ssh import (
    SSHKeyManager,
    SSHKeyInfo,
    SSHKeyMetadata,
    SSHKeyOutput,
    SSHBundleMetadata,
    SSHBundleOutput,
    SSHCertConfig,
    derive_ssh_key,
    bundle_ssh_ca,
)
from degen_crypto.lib_common import EntropyMetrics
from degen_crypto.lib_crypto_asym import AsymmetricKeyGenerator


class TestSSHKeyManager:
    """Test suite for SSHKeyManager class."""

    def test_derive_ssh_seed_deterministic(self):
        """Test that SSH seed derivation is deterministic."""
        seed = "test-seed-phrase"
        hostname = "testhost"
        index = 0

        seed1, metrics1 = SSHKeyManager.derive_ssh_seed(seed, hostname, index)
        seed2, metrics2 = SSHKeyManager.derive_ssh_seed(seed, hostname, index)

        assert seed1 == seed2
        assert len(seed1) == 32
        assert isinstance(metrics1, dict)

    def test_derive_ssh_seed_different_hostname(self):
        """Test that different hostnames produce different seeds."""
        seed = "test-seed-phrase"
        index = 0

        seed1, _ = SSHKeyManager.derive_ssh_seed(seed, "host1", index)
        seed2, _ = SSHKeyManager.derive_ssh_seed(seed, "host2", index)

        assert seed1 != seed2

    def test_derive_ssh_seed_different_index(self):
        """Test that different indexes produce different seeds."""
        seed = "test-seed-phrase"
        hostname = "testhost"

        seed1, _ = SSHKeyManager.derive_ssh_seed(seed, hostname, 0)
        seed2, _ = SSHKeyManager.derive_ssh_seed(seed, hostname, 1)

        assert seed1 != seed2

    def test_generate_ed25519_keypair_deterministic(self):
        """Test Ed25519 keypair public key is deterministic."""
        seed_bytes = b"0" * 32

        key1 = AsymmetricKeyGenerator.generate_ed25519_key(seed_bytes)
        priv1, pub1 = SSHKeyManager.serialize_keypair(key1)
        key2 = AsymmetricKeyGenerator.generate_ed25519_key(seed_bytes)
        priv2, pub2 = SSHKeyManager.serialize_keypair(key2)

        # Public key should be deterministic
        assert pub1 == pub2
        # Note: Private key format may have random padding, but the key itself is deterministic

    def test_generate_ed25519_keypair_structure(self):
        """Test Ed25519 keypair structure."""
        seed_bytes = b"0" * 32

        ed25519_key = AsymmetricKeyGenerator.generate_ed25519_key(seed_bytes)
        private_key, public_key = SSHKeyManager.serialize_keypair(ed25519_key)

        assert isinstance(private_key, str)
        assert isinstance(public_key, str)
        assert private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert public_key.startswith("ssh-ed25519 ")

    def test_generate_rsa_keypair_structure(self):
        """Test RSA keypair structure."""
        seed_bytes = b"0" * 32

        rsa_key = AsymmetricKeyGenerator.generate_rsa_key(seed_bytes, key_size=2048)
        private_key, public_key = SSHKeyManager.serialize_keypair(rsa_key)

        assert isinstance(private_key, str)
        assert isinstance(public_key, str)
        assert private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert public_key.startswith("ssh-rsa ")

    def test_generate_ecdsa_keypair_structure(self):
        """Test ECDSA keypair structure."""
        seed_bytes = b"0" * 32

        ecdsa_key = AsymmetricKeyGenerator.generate_ec_key(seed_bytes, curve_name="secp256r1")
        private_key, public_key = SSHKeyManager.serialize_keypair(ecdsa_key)

        assert isinstance(private_key, str)
        assert isinstance(public_key, str)
        assert private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert public_key.startswith("ecdsa-sha2-nistp256 ")

    def test_generate_all_ssh_keys_single_type(self):
        """Test generating single key type."""
        seed_phrase = "test-seed"
        hostname = "testhost"
        index = 0

        result = SSHKeyManager.generate_all_ssh_keys(seed_phrase, hostname, index, types=["ed25519"])

        assert isinstance(result, dict)
        assert "ed25519" in result
        assert isinstance(result["ed25519"], SSHKeyInfo)

    def test_generate_all_ssh_keys_all_types(self):
        """Test generating all key types."""
        seed_phrase = "test-seed"
        hostname = "testhost"
        index = 0

        result = SSHKeyManager.generate_all_ssh_keys(seed_phrase, hostname, index, types=["ed25519", "rsa", "ecdsa"])

        assert isinstance(result, dict)
        assert "ed25519" in result
        assert "rsa" in result
        assert "ecdsa" in result

    def test_generate_all_ssh_keys_random(self):
        """Test random key generation when seed is not provided."""
        hostname = "randomhost"
        index = 0

        result1 = SSHKeyManager.generate_all_ssh_keys(None, hostname, index, types=["ed25519"])
        result2 = SSHKeyManager.generate_all_ssh_keys(None, hostname, index, types=["ed25519"])

        assert result1["ed25519"].deterministic is False
        assert result2["ed25519"].deterministic is False
        assert result1["ed25519"].public_key != result2["ed25519"].public_key


class TestSSHCertConfig:
    """Test suite for SSHCertConfig validation."""

    def test_ssh_cert_config_minimal(self):
        """Test minimal certificate configuration."""
        config = SSHCertConfig(
            cert_type="user",
            principals=["user1"],
            key_id="test@example.com",
            valid_from=1704067200,  # 2024-01-01T00:00:00Z in Unix epoch
            valid_to=1735689600     # 2025-01-01T00:00:00Z in Unix epoch
        )

        assert config.cert_type == "user"
        assert config.principals == ["user1"]
        assert config.key_id == "test@example.com"

    def test_ssh_cert_config_validate_principals_empty(self):
        """Test that empty principals list raises error."""
        try:
            SSHCertConfig(
                cert_type="user",
                principals=[],
                key_id="test",
                valid_from=1704067200,  # 2024-01-01T00:00:00Z in Unix epoch
                valid_to=1735689600     # 2025-01-01T00:00:00Z in Unix epoch
            )
            assert False, "Should have raised validation error"
        except Exception as e:
            assert "at least 1 item" in str(e).lower() or "at least one principal" in str(e).lower()

    def test_ssh_cert_config_host_certificate(self):
        """Test host certificate configuration."""
        config = SSHCertConfig(
            cert_type="host",
            principals=["example.com", "www.example.com"],
            key_id="host.example.com",
            valid_from=1704067200,  # 2024-01-01T00:00:00Z in Unix epoch
            valid_to=1735689600     # 2025-01-01T00:00:00Z in Unix epoch
        )

        assert config.cert_type == "host"
        assert len(config.principals) == 2

    def test_ssh_cert_config_with_extensions(self):
        """Test certificate with extensions."""
        config = SSHCertConfig(
            cert_type="user",
            principals=["user1"],
            key_id="test",
            valid_from=1704067200,  # 2024-01-01T00:00:00Z in Unix epoch
            valid_to=1735689600,    # 2025-01-01T00:00:00Z in Unix epoch
            extensions={
                "permit-X11-forwarding": "",
                "permit-agent-forwarding": "",
                "permit-port-forwarding": "",
                "permit-pty": "",
                "permit-user-rc": ""
            }
        )

        assert config.extensions.get("permit-X11-forwarding") == ""
        assert config.extensions.get("permit-agent-forwarding") == ""


class TestSSHModels:
    """Test suite for SSH-related Pydantic models."""

    def test_ssh_key_info_model(self):
        """Test SSHKeyInfo model."""
        key_info = SSHKeyInfo(
            private_key="-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----",
            public_key="ssh-ed25519 AAAA... test@host",
            algorithm="ed25519",
            use_case="General purpose, recommended",
            key_size="256 bits (curve25519)",
            deterministic=True,
            filename="id_ed25519_test_0"
        )

        assert key_info.algorithm == "ed25519"
        assert key_info.deterministic is True

    def test_ssh_key_metadata_model(self):
        """Test SSHKeyMetadata model."""
        entropy = EntropyMetrics(
            length=10,
            shannon_entropy_bits=3.0,
            min_entropy_bits=2.0,
            relative_entropy=0.5,
            estimated_strength_bits=30.0,
            quality="fair"
        )

        metadata = SSHKeyMetadata(
            derivation_path="testhost/0",
            derivation_method="PBKDF2-HMAC-SHA512",
            iterations=2048,
            note="Test note",
            recommended="ed25519",
            seed_entropy=entropy
        )

        assert metadata.derivation_path == "testhost/0"
        assert metadata.iterations == 2048

    def test_ssh_key_output_single_key(self):
        """Test SSHKeyOutput for single key."""
        metadata = SSHKeyMetadata(
            derivation_path="test/0",
            derivation_method="PBKDF2-HMAC-SHA512",
            iterations=2048
        )

        output = SSHKeyOutput(
            hostname="testhost",
            index=0,
            key_type="ed25519",
            private_key="-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----",
            public_key="ssh-ed25519 AAAA... test",
            _metadata=metadata
        )

        assert output.hostname == "testhost"
        assert output.key_type == "ed25519"
        assert output.keys is None

    def test_ssh_bundle_output_model(self):
        """Test SSHBundleOutput model."""
        metadata = SSHBundleMetadata(
            bundled_from_files=True,
            key_type="ed25519",
            public_key_generated=False
        )

        output = SSHBundleOutput(
            private_key="-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----",
            public_key="ssh-ed25519 AAAA... test",
            _metadata=metadata
        )

        assert output.private_key is not None
        assert output.public_key is not None


class TestDeriveSSHKeyCommand:
    """Test suite for derive-ssh-key CLI command."""

    def test_derive_ssh_key_basic(self):
        """Test basic SSH key generation."""
        runner = CliRunner()
        result = runner.invoke(derive_ssh_key, [
            "--hostname", "testhost",
            "--seed", "test-seed-phrase"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["hostname"] == "testhost"
        assert output["index"] == 0
        assert output["key_type"] == "ed25519"
        assert "private_key" in output
        assert "public_key" in output

    def test_derive_ssh_key_with_index(self):
        """Test SSH key generation with custom index."""
        runner = CliRunner()
        result = runner.invoke(derive_ssh_key, [
            "--hostname", "testhost",
            "--seed", "test-seed",
            "--index", "5"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["index"] == 5

    def test_derive_ssh_key_all_types(self):
        """Test generating all key types."""
        runner = CliRunner()
        result = runner.invoke(derive_ssh_key, [
            "--hostname", "testhost",
            "--seed", "test-seed",
            "--all-types"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert "keys" in output
        assert "ed25519" in output["keys"]
        assert "rsa" in output["keys"]
        assert "ecdsa" in output["keys"]

    def test_derive_ssh_key_pretty_output(self):
        """Test pretty-printed output."""
        runner = CliRunner()
        result = runner.invoke(derive_ssh_key, [
            "--hostname", "testhost",
            "--seed", "test-seed",
            "--pretty"
        ])

        assert result.exit_code == 0
        # Pretty print should have indentation
        assert "  " in result.output

    def test_derive_ssh_key_deterministic_public_key(self):
        """Test that same seed produces same public key."""
        runner = CliRunner()

        result1 = runner.invoke(derive_ssh_key, [
            "--hostname", "testhost",
            "--seed", "same-seed"
        ])
        result2 = runner.invoke(derive_ssh_key, [
            "--hostname", "testhost",
            "--seed", "same-seed"
        ])

        assert result1.exit_code == 0
        assert result2.exit_code == 0

        output1 = json.loads(result1.output)
        output2 = json.loads(result2.output)

        # Public key should be deterministic
        assert output1["public_key"] == output2["public_key"]


class TestBundleSSHCACommand:
    """Test suite for bundle-ssh-ca CLI command."""

    def test_bundle_ssh_ca_from_files(self):
        """Test bundling SSH CA from files."""
        runner = CliRunner()

        # Generate test keys
        seed_bytes, _ = SSHKeyManager.derive_ssh_seed("test-seed", "ca", 0)
        ca_key = AsymmetricKeyGenerator.generate_ed25519_key(seed_bytes)
        private_key, public_key = SSHKeyManager.serialize_keypair(ca_key)

        # Write to temp files
        with runner.isolated_filesystem():
            with open("ca_key", "w") as f:
                f.write(private_key)
            with open("ca_key.pub", "w") as f:
                f.write(public_key)

            result = runner.invoke(bundle_ssh_ca, [
                "--private-key", "ca_key",
                "--public-key", "ca_key.pub"
            ])

            assert result.exit_code == 0
            output = json.loads(result.output)
            assert "private_key" in output
            assert "public_key" in output
            assert "_metadata" in output

    def test_bundle_ssh_ca_pretty_output(self):
        """Test pretty-printed bundle output."""
        runner = CliRunner()

        seed_bytes, _ = SSHKeyManager.derive_ssh_seed("test-seed", "ca", 0)
        ca_key = AsymmetricKeyGenerator.generate_ed25519_key(seed_bytes)
        private_key, public_key = SSHKeyManager.serialize_keypair(ca_key)

        with runner.isolated_filesystem():
            with open("ca_key", "w") as f:
                f.write(private_key)
            with open("ca_key.pub", "w") as f:
                f.write(public_key)

            result = runner.invoke(bundle_ssh_ca, [
                "--private-key", "ca_key",
                "--public-key", "ca_key.pub",
                "--pretty"
            ])

            assert result.exit_code == 0
            assert "  " in result.output


class TestIntegration:
    """Integration tests for SSH functionality."""

    def test_end_to_end_ssh_key_workflow(self):
        """Test complete SSH key generation workflow."""
        seed = "my-infrastructure-seed"
        hostname = "production-server"
        index = 0

        # Generate keys
        result = SSHKeyManager.generate_all_ssh_keys(seed, hostname, index, types=["ed25519", "rsa", "ecdsa"])

        # Verify structure
        assert isinstance(result, dict)
        assert len(result) == 3

        # Verify all key types present
        assert "ed25519" in result
        assert "rsa" in result
        assert "ecdsa" in result

        # Verify key info structure
        assert isinstance(result["ed25519"], SSHKeyInfo)
        assert result["ed25519"].deterministic is True

    def test_ssh_key_formats_valid(self):
        """Test that generated keys are in valid formats."""
        result = SSHKeyManager.generate_all_ssh_keys("test-seed", "test", 0, types=["ed25519", "rsa", "ecdsa"])

        # Check Ed25519
        assert result["ed25519"].private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert result["ed25519"].public_key.startswith("ssh-ed25519 ")

        # Check RSA
        assert result["rsa"].private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert result["rsa"].public_key.startswith("ssh-rsa ")

        # Check ECDSA
        assert result["ecdsa"].private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert result["ecdsa"].public_key.startswith("ecdsa-sha2-nistp256 ")

    def test_cli_workflow_determinism(self):
        """Test that CLI produces deterministic output."""
        runner = CliRunner()

        # Generate key twice with same seed
        result1 = runner.invoke(derive_ssh_key, [
            "--hostname", "server1",
            "--seed", "my-seed",
            "--index", "0"
        ])

        result2 = runner.invoke(derive_ssh_key, [
            "--hostname", "server1",
            "--seed", "my-seed",
            "--index", "0"
        ])

        assert result1.exit_code == 0
        assert result2.exit_code == 0

        output1 = json.loads(result1.output)
        output2 = json.loads(result2.output)

        # Public keys should match (Ed25519 is deterministic)
        assert output1["public_key"] == output2["public_key"]

    def test_different_indexes_produce_different_keys(self):
        """Test that different indexes produce different keys."""
        runner = CliRunner()

        result0 = runner.invoke(derive_ssh_key, [
            "--hostname", "server",
            "--seed", "seed",
            "--index", "0"
        ])

        result1 = runner.invoke(derive_ssh_key, [
            "--hostname", "server",
            "--seed", "seed",
            "--index", "1"
        ])

        assert result0.exit_code == 0
        assert result1.exit_code == 0

        output0 = json.loads(result0.output)
        output1 = json.loads(result1.output)

        # Different indexes should produce different keys
        assert output0["public_key"] != output1["public_key"]

    def test_seed_entropy_included_in_metadata(self):
        """Test that entropy metrics are included in output."""
        runner = CliRunner()

        result = runner.invoke(derive_ssh_key, [
            "--hostname", "server",
            "--seed", "my-test-seed-phrase-with-good-entropy"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)

        assert "_metadata" in output
        assert "seed_entropy" in output["_metadata"]
        assert output["_metadata"]["seed_entropy"]["length"] > 0
