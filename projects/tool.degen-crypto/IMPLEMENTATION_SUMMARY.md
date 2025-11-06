# PGP Deterministic Key Generation - Implementation Summary

## Date: November 2, 2025

## Problem Statement

The PGP key generation implementation in `tool_pgp.py` was **not truly deterministic**:

1. **Root Cause**: While deterministic cryptographic keys were being generated from seed phrases using PBKDF2-HMAC-SHA512, they were immediately **discarded**
2. **Actual Behavior**: `pgpy.PGPKey.new()` was generating fresh random keys on every invocation
3. **Secondary Issue**: No control over creation timestamps caused different fingerprints even with same key material

## Solution Implemented

### 1. Manual PGP Packet Construction

**Location**: `pkg/degen_crypto/tool_pgp.py:120-202`

Created three new methods to properly populate PGP key packets with deterministic key material:

- `_populate_rsa_key_material()` - Converts RSA keys from cryptography library to PGPy MPI format
- `_populate_ecdsa_key_material()` - Converts ECDSA keys with proper curve OID and point encoding
- `_populate_ed25519_key_material()` - Converts Ed25519 keys with native point format

**Key Implementation Details**:
```python
# Instead of random generation:
# pgp_key = pgpy.PGPKey.new(PubKeyAlgorithm.EdDSA, EllipticCurveOID.Ed25519)

# We now manually construct packets:
pk = PrivKeyV4()
pk.pkalg = PubKeyAlgorithm.EdDSA
pk.created = fixed_timestamp
cls._populate_ed25519_key_material(crypto_key, pk)
pk.update_hlen()
```

### 2. Fixed Timestamp for Reproducibility

**Location**: `pkg/degen_crypto/tool_pgp.py:230-234`

```python
# Default timestamp for deterministic generation
if created_timestamp is None:
    created_timestamp = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
```

**Why This Works**:
- PGP fingerprints are SHA-1 hashes that include: `version || timestamp || algorithm || key_material`
- Same timestamp + same key material = same fingerprint
- Security is NOT affected by fixed timestamp (only metadata)

### 3. Complete Rewrite of Key Creation

**Location**: `pkg/degen_crypto/tool_pgp.py:294-364`

Replaced `_create_pgp_key_from_crypto()` to:
1. Create empty `PrivKeyV4()` packet
2. Set fixed creation timestamp
3. Set algorithm type (RSA/Ed25519/ECDSA)
4. Populate with deterministically-derived key material
5. Update packet headers
6. Add user ID and preferences

### 4. Package Configuration Fixes

**Location**: `pyproject.toml`

Fixed package structure to properly expose the `degen-crypto` command:

```toml
[project.scripts]
degen-crypto = "degen_crypto.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["pkg/degen_crypto"]

[tool.pytest.ini_options]
addopts = [
    "--cov=degen_crypto",
    ...
]
```

## Test Results

### Determinism Verification

All three key types generate deterministic keys:

```
Testing Deterministic PGP Key Generation
==================================================

ED25519:
  First:  749BB32CAAE9D5A5C584504C5DB546B2CA293DB2
  Second: 749BB32CAAE9D5A5C584504C5DB546B2CA293DB2
  ✓ DETERMINISTIC

RSA:
  First:  0F5BBDA408A4AD1C13D5DE55755ACA4BEB3181FE
  Second: 0F5BBDA408A4AD1C13D5DE55755ACA4BEB3181FE
  ✓ DETERMINISTIC

ECDSA:
  First:  0A0279E6F8C850E61E03097A4A80C38B10C6522B
  Second: 0A0279E6F8C850E61E03097A4A80C38B10C6522B
  ✓ DETERMINISTIC
```

### Full Test Suite

**32 tests passing** including:
- Previously skipped determinism tests (now re-enabled)
- All key type tests (RSA, Ed25519, ECDSA)
- CLI command tests
- Integration tests
- Model serialization tests

```
======================== 32 passed, 1 warning in 20.61s ========================
```

## Documentation

### 1. Updated Module Documentation

**Location**: `pkg/degen_crypto/tool_pgp.py:1-31`

Added comprehensive module docstring explaining:
- Deterministic features
- Implementation approach
- Fixed timestamp rationale
- Security considerations

### 2. Created USER_GUIDE.md

**Location**: `USER_GUIDE.md` (400+ lines)

Complete user guide including:
- Overview of all 8 CLI commands
- Examples for password hashing, SSH, PGP, X.509
- Advanced usage (contexts, scripting)
- Security best practices
- Troubleshooting guide

## Example Usage

### Generate Deterministic PGP Identity

```bash
# First generation
degen-crypto derive-pgp-identity \
  --name "Alice Anderson" \
  --email "alice@example.com" \
  --seed "my-secure-seed" \
  --key-type ed25519 \
  --with-subkeys \
  --pretty

# Second generation - SAME fingerprint!
degen-crypto derive-pgp-identity \
  --name "Alice Anderson" \
  --email "alice@example.com" \
  --seed "my-secure-seed" \
  --key-type ed25519 \
  --with-subkeys \
  --pretty
```

### Generate Multiple Keys from Same Seed

```bash
# Use different contexts for different keys
degen-crypto derive-pgp-key \
  --identity "user@example.com" \
  --seed "master-seed" \
  --context "pgp/production/sign" \
  --key-type ed25519 \
  --purpose sign

degen-crypto derive-pgp-key \
  --identity "user@example.com" \
  --seed "master-seed" \
  --context "pgp/production/encrypt" \
  --key-type ed25519 \
  --purpose encrypt
```

## Technical Details

### Key Material Conversion

**RSA Keys**:
```python
pk.keymaterial.n = MPI(public_numbers.n)      # Modulus
pk.keymaterial.e = MPI(public_numbers.e)      # Public exponent
pk.keymaterial.d = MPI(private_numbers.d)     # Private exponent
pk.keymaterial.p = MPI(private_numbers.p)     # Prime p
pk.keymaterial.q = MPI(private_numbers.q)     # Prime q
pk.keymaterial.u = MPI(rsa_crt_iqmp(q, p))    # u = p^-1 mod q
```

**Ed25519 Keys**:
```python
public_bytes = crypto_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw
)
pk.keymaterial.p = ECPoint.from_values(
    EllipticCurveOID.Ed25519.key_size,
    ECPointFormat.Native,
    public_bytes
)
private_int = int.from_bytes(private_bytes, byteorder='big')
pk.keymaterial.s = MPI(private_int)
```

**ECDSA Keys**:
```python
pk.keymaterial.oid = curve_oid  # e.g., NIST_P256
pk.keymaterial.p = ECPoint.from_values(
    curve_oid.key_size,
    ECPointFormat.Standard,
    MPI(public_numbers.x),
    MPI(public_numbers.y)
)
pk.keymaterial.s = MPI(private_numbers.private_value)
```

### Fingerprint Calculation

PGP fingerprints are SHA-1 hashes of the packet structure:

```
fingerprint = SHA1(
    0x99                        # Packet tag
    || packet_length            # 2 bytes
    || 0x04                     # Version
    || timestamp                # 4 bytes (Unix time)
    || algorithm                # 1 byte
    || key_material             # Variable length
)
```

By fixing the timestamp to `2020-01-01 00:00:00 UTC` (Unix timestamp: `1577836800`), we ensure:
- Same seed → same key material → same fingerprint
- Reproducible across runs, machines, and time

### Security Considerations

1. **Fixed Timestamp**: Does NOT affect cryptographic security
   - Timestamp is metadata, not part of key generation
   - Key strength comes from seed entropy and derivation function
   - Only affects key identification (fingerprint)

2. **Seed Entropy**: Critical for security
   - Tool analyzes and reports seed entropy
   - Warns if entropy is weak (<80 bits)
   - Recommends 128+ bits for production

3. **Context Separation**: Prevents key reuse
   - Different contexts → different keys from same seed
   - Protects against cross-domain attacks

## Files Modified

1. `pkg/degen_crypto/tool_pgp.py` - Core implementation
2. `pkg/degen_crypto/tests/tool_pgp.py` - Re-enabled determinism tests
3. `pyproject.toml` - Package configuration and command name
4. `USER_GUIDE.md` - Created comprehensive documentation

## Files Created

1. `USER_GUIDE.md` - Complete user guide with examples
2. `IMPLEMENTATION_SUMMARY.md` - This document

## Breaking Changes

### Command Renamed

- **Old**: `crypto-tools`
- **New**: `degen-crypto`

### Install/Reinstall Required

```bash
# Uninstall old version
uv pip uninstall crypto-tools

# Install new version
uv pip install -e .

# Verify
degen-crypto --help
```

## Future Enhancements

### Potential Improvements

1. **Custom Timestamp Parameter**: Allow users to specify creation timestamp
   ```bash
   degen-crypto derive-pgp-key ... --created-timestamp "2024-01-01"
   ```

2. **Seed-Derived Timestamp**: Derive timestamp from seed hash
   ```python
   timestamp = base_epoch + (hash(seed) % one_year)
   ```

3. **Subkey Binding**: Ensure subkeys are properly bound to primary key with deterministic signatures

4. **Key Export Helpers**: Add convenience commands for common export formats
   ```bash
   degen-crypto export-to-gpg ...
   degen-crypto export-to-keybase ...
   ```

## Conclusion

The implementation now provides **fully deterministic PGP key generation** across all supported key types (RSA, Ed25519, ECDSA). The same seed phrase and context will always produce the exact same fingerprint, enabling:

- ✅ Infrastructure as Code with reproducible keys
- ✅ Disaster recovery from backed-up seeds
- ✅ Key rotation with context separation
- ✅ Consistent key derivation across environments

All tests pass, documentation is complete, and the tool is production-ready.

---

**Author**: Claude (Anthropic)
**Date**: November 2, 2025
**Version**: 0.1.0
