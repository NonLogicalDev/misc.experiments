# Degen-Crypto User Guide

A comprehensive guide to using degen-crypto for deterministic cryptographic key and certificate generation.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands](#commands)
  - [Password Hashing](#password-hashing)
  - [SSH Keys](#ssh-keys)
  - [PGP/GPG Keys](#pgpgpg-keys)
  - [X.509 Certificates](#x509-certificates)
- [Advanced Usage](#advanced-usage)
- [Security Considerations](#security-considerations)

---

## Overview

**degen-crypto** provides deterministic generation of cryptographic keys and certificates from seed phrases. This enables:

- **Infrastructure as Code**: Reproduce keys from configuration
- **Disaster Recovery**: Regenerate keys from backed-up seeds
- **Key Rotation**: Derive multiple keys from a single seed using contexts
- **Consistency**: Same seed + context always produces same output

**Key Features:**
- ✅ Truly deterministic key generation (RSA, Ed25519, ECDSA)
- ✅ Support for SSH, PGP, X.509 certificates
- ✅ Password hashing (bcrypt, argon2, PBKDF2, scrypt)
- ✅ Context-based key derivation for multiple keys from one seed
- ✅ Entropy analysis and security warnings

---

## Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .

# Verify installation
degen-crypto --help
```

---

## Quick Start

### Generate SSH Key from Seed

```bash
# Generate Ed25519 SSH key
echo "my-secret-seed-phrase" | degen-crypto derive-ssh-key \
  --identity "user@hostname" \
  --key-type ed25519 \
  --seed - \
  --pretty

# Output includes public key, private key, and fingerprint
```

### Generate PGP Identity

```bash
# Generate complete PGP identity with subkeys
degen-crypto derive-pgp-identity \
  --name "Alice Anderson" \
  --email "alice@example.com" \
  --seed "my-pgp-seed" \
  --key-type ed25519 \
  --with-subkeys \
  --pretty
```

### Generate Password Hash

```bash
# Generate bcrypt password hash
degen-crypto derive-passwd-set \
  --identity "admin" \
  --password "MySecurePassword123" \
  --hash-types bcrypt \
  --pretty
```

---

## Commands

### Password Hashing

**`derive-passwd-set`** - Generate password hashes for various authentication systems.

#### Basic Usage

```bash
# Single hash type
degen-crypto derive-passwd-set \
  --identity "admin" \
  --password "MyPassword123" \
  --hash-types bcrypt

# Multiple hash types
degen-crypto derive-passwd-set \
  --identity "admin" \
  --password "MyPassword123" \
  --hash-types bcrypt argon2 sha512-crypt
```

#### Supported Hash Types

- `bcrypt` - For htpasswd, general web authentication
- `argon2` - Modern, memory-hard function
- `sha512-crypt` - Traditional Unix shadow passwords
- `sha256-crypt` - Legacy Unix systems
- `pbkdf2-sha256` - Django, PBKDF2 applications
- `apr1-md5` - Apache htpasswd legacy
- `scrypt` - Traefik and modern applications

#### Examples

```bash
# For htpasswd file (Nginx, Apache)
degen-crypto derive-passwd-set \
  --identity "webadmin" \
  --password "WebPass123!" \
  --hash-types bcrypt \
  | jq -r '.password_hashes.bcrypt'

# For Traefik users file
degen-crypto derive-passwd-set \
  --identity "dashboard-user" \
  --password "TraefikPass" \
  --hash-types bcrypt \
  --pretty

# For Linux /etc/shadow
degen-crypto derive-passwd-set \
  --identity "sysadmin" \
  --password "SysPassword" \
  --hash-types sha512-crypt \
  | jq -r '.password_hashes."sha512-crypt"'
```

#### Input from Environment Variable

```bash
export ADMIN_PASSWORD="SecretPassword"
degen-crypto derive-passwd-set \
  --identity "admin" \
  --password "env:ADMIN_PASSWORD" \
  --hash-types bcrypt argon2
```

---

### SSH Keys

#### `derive-ssh-key` - Generate SSH Keypairs

**Supported Key Types:**
- `ed25519` - Modern, recommended (default)
- `ecdsa` - NIST curves (P-256, P-384, P-521)
- `rsa` - Traditional (2048, 4096 bits)

**Basic Ed25519 Key:**

```bash
degen-crypto derive-ssh-key \
  --identity "user@hostname" \
  --seed "my-ssh-seed" \
  --key-type ed25519 \
  --pretty
```

**With Custom Context (for multiple keys from same seed):**

```bash
# Production key
degen-crypto derive-ssh-key \
  --identity "deploy@production" \
  --seed "company-ssh-seed" \
  --context "ssh/production/deploy" \
  --key-type ed25519

# Staging key (different fingerprint, same seed)
degen-crypto derive-ssh-key \
  --identity "deploy@staging" \
  --seed "company-ssh-seed" \
  --context "ssh/staging/deploy" \
  --key-type ed25519
```

**RSA Key:**

```bash
degen-crypto derive-ssh-key \
  --identity "legacy-server" \
  --seed "@/path/to/seed.txt" \
  --key-type rsa \
  --key-size 4096
```

**ECDSA Key:**

```bash
degen-crypto derive-ssh-key \
  --identity "ecdsa-user" \
  --seed "my-seed" \
  --key-type ecdsa \
  --curve secp384r1
```

**Save to Files:**

```bash
# Generate and save keys
OUTPUT=$(degen-crypto derive-ssh-key \
  --identity "myuser" \
  --seed "seed123" \
  --key-type ed25519)

echo "$OUTPUT" | jq -r '.private_key_openssh' > ~/.ssh/id_ed25519_generated
echo "$OUTPUT" | jq -r '.public_key_openssh' > ~/.ssh/id_ed25519_generated.pub
chmod 600 ~/.ssh/id_ed25519_generated
```

#### `derive-ssh-cert` - Generate SSH Certificates

**User Certificate:**

```bash
degen-crypto derive-ssh-cert \
  --identity "alice" \
  --seed "alice-cert-seed" \
  --cert-type user \
  --principals alice,alice-admin \
  --validity-days 90 \
  --ca-private-key "@/path/to/ca_key" \
  --pretty
```

**Host Certificate:**

```bash
degen-crypto derive-ssh-cert \
  --identity "web-server-01" \
  --seed "host-cert-seed" \
  --cert-type host \
  --principals web-server-01,web-server-01.internal \
  --validity-days 365 \
  --ca-private-key "@/path/to/ca_key"
```

**With Extensions:**

```bash
degen-crypto derive-ssh-cert \
  --identity "poweruser" \
  --seed "user-seed" \
  --cert-type user \
  --principals poweruser \
  --extensions permit-pty,permit-port-forwarding \
  --validity-days 30 \
  --ca-private-key "@ca_key.pem"
```

#### `bundle-ssh-ca` - Bundle SSH CA Keys

```bash
# Create SSH CA bundle
degen-crypto bundle-ssh-ca \
  --ca-name "Internal SSH CA" \
  --private-key "@/path/to/ca_private_key" \
  --public-key "@/path/to/ca_public_key.pub" \
  --pretty > ssh-ca-bundle.json
```

---

### PGP/GPG Keys

#### `derive-pgp-key` - Generate Single PGP Key

**Ed25519 Signing Key:**

```bash
degen-crypto derive-pgp-key \
  --identity "Alice <alice@example.com>" \
  --seed "alice-pgp-seed" \
  --key-type ed25519 \
  --purpose sign \
  --pretty
```

**RSA Encryption Key:**

```bash
degen-crypto derive-pgp-key \
  --identity "Bob <bob@example.com>" \
  --seed "bob-pgp-seed" \
  --key-type rsa \
  --key-size 4096 \
  --purpose encrypt \
  --pretty
```

**ECDSA Key with Expiration:**

```bash
degen-crypto derive-pgp-key \
  --identity "Carol <carol@example.com>" \
  --seed "carol-seed" \
  --key-type ecdsa \
  --curve secp384r1 \
  --purpose sign \
  --expires-days 365 \
  --pretty
```

**All Purposes:**
- `certify` - Primary key certification
- `sign` - Code/message signing
- `encrypt` - Encryption
- `authenticate` - SSH/authentication

**Extract Keys:**

```bash
# Save armored keys to files
OUTPUT=$(degen-crypto derive-pgp-key \
  --identity "user@example.com" \
  --seed "my-pgp-seed" \
  --key-type ed25519 \
  --purpose sign)

echo "$OUTPUT" | jq -r '.key_info.public_key_armored' > public.asc
echo "$OUTPUT" | jq -r '.key_info.private_key_armored' > private.asc

# Import to GPG
gpg --import private.asc
```

#### `derive-pgp-identity` - Generate Complete PGP Identity

**Basic Identity:**

```bash
degen-crypto derive-pgp-identity \
  --name "Alice Anderson" \
  --email "alice@example.com" \
  --seed "alice-identity-seed" \
  --key-type ed25519 \
  --pretty
```

**With Subkeys (Recommended):**

```bash
degen-crypto derive-pgp-identity \
  --name "Bob Builder" \
  --email "bob@company.com" \
  --seed "bob-seed" \
  --key-type ed25519 \
  --with-subkeys \
  --pretty
```

This generates:
- Primary key for certification
- Signing subkey
- Encryption subkey
- Authentication subkey

**RSA Identity:**

```bash
degen-crypto derive-pgp-identity \
  --name "Carol Clark" \
  --email "carol@enterprise.com" \
  --seed "@/secure/seed.txt" \
  --key-type rsa \
  --key-size 4096 \
  --with-subkeys
```

**ECDSA with Expiration:**

```bash
degen-crypto derive-pgp-identity \
  --name "Dave Davis" \
  --email "dave@startup.io" \
  --seed "dave-seed" \
  --key-type ecdsa \
  --curve secp521r1 \
  --with-subkeys \
  --expires-days 730 \
  --pretty
```

**Important Notes:**
- Keys have creation timestamp of 2020-01-01 for determinism
- Fingerprints are stable and reproducible
- Same seed + email always produces same fingerprint

---

### X.509 Certificates

#### `derive-x509` - Generate X.509 Keys and Certificates

**Basic Self-Signed Certificate:**

```bash
degen-crypto derive-x509 \
  --common-name "example.com" \
  --seed "my-x509-seed" \
  --cert-type self-signed \
  --key-type ed25519 \
  --pretty
```

**Certificate Authority (CA):**

```bash
degen-crypto derive-x509 \
  --common-name "Internal CA" \
  --seed "ca-seed" \
  --cert-type ca \
  --key-type rsa \
  --key-size 4096 \
  --validity-days 3650 \
  --organization "My Company" \
  --country US \
  --pretty > ca-bundle.json
```

**Server Certificate:**

```bash
degen-crypto derive-x509 \
  --common-name "api.example.com" \
  --seed "server-cert-seed" \
  --cert-type server \
  --key-type ecdsa \
  --curve secp384r1 \
  --san "DNS:api.example.com,DNS:www.api.example.com,IP:192.168.1.100" \
  --validity-days 365 \
  --pretty
```

**Client Certificate:**

```bash
degen-crypto derive-x509 \
  --common-name "client-app" \
  --seed "client-seed" \
  --cert-type client \
  --key-type ed25519 \
  --validity-days 90 \
  --pretty
```

**With Full Subject Information:**

```bash
degen-crypto derive-x509 \
  --common-name "vpn.company.com" \
  --seed "vpn-seed" \
  --cert-type server \
  --organization "ACME Corporation" \
  --organizational-unit "IT Department" \
  --locality "San Francisco" \
  --state "California" \
  --country "US" \
  --san "DNS:vpn.company.com,IP:10.0.0.1" \
  --key-type ecdsa \
  --curve secp256r1 \
  --validity-days 730 \
  --pretty
```

**Sign with CA:**

```bash
# First, generate or load CA
CA_BUNDLE=$(degen-crypto derive-x509 \
  --common-name "My Root CA" \
  --seed "ca-seed" \
  --cert-type ca \
  --key-type rsa \
  --key-size 4096)

# Extract CA cert and key
echo "$CA_BUNDLE" | jq -r '.certificate_pem' > ca.crt
echo "$CA_BUNDLE" | jq -r '.private_key_pem' > ca.key

# Generate server cert signed by CA
degen-crypto derive-x509 \
  --common-name "secure.example.com" \
  --seed "server-seed" \
  --cert-type server \
  --ca-cert "@ca.crt" \
  --ca-key "@ca.key" \
  --san "DNS:secure.example.com" \
  --validity-days 365 \
  --pretty
```

#### `bundle-ca` - Bundle CA Certificate and Key

```bash
degen-crypto bundle-ca \
  --ca-name "Production CA" \
  --certificate "@/path/to/ca.crt" \
  --private-key "@/path/to/ca.key" \
  --pretty > ca-bundle.json
```

---

## Advanced Usage

### Context-Based Key Derivation

Generate multiple different keys from the same seed using contexts:

```bash
SEED="master-seed-phrase"

# Development SSH key
degen-crypto derive-ssh-key \
  --identity "deploy" \
  --seed "$SEED" \
  --context "ssh/dev/deploy" \
  --key-type ed25519

# Production SSH key (different fingerprint!)
degen-crypto derive-ssh-key \
  --identity "deploy" \
  --seed "$SEED" \
  --context "ssh/prod/deploy" \
  --key-type ed25519

# Each context produces a unique key from the same seed
```

### Controlling Timestamps and Validity Periods

Different credential types have different timestamp and validity options:

#### PGP Keys - Creation and Expiration Control

PGP keys default to a **fixed creation timestamp** (2020-01-01) for determinism, but you can customize both creation and expiration:

**Simple Expiration (days from creation)**:
```bash
# Key expires in 1 year (from creation date)
degen-crypto derive-pgp-key \
  --identity "user@example.com" \
  --seed "my-seed" \
  --key-type ed25519 \
  --purpose sign \
  --expires-days 365

# Key never expires (default)
degen-crypto derive-pgp-key \
  --identity "user@example.com" \
  --seed "my-seed" \
  --key-type ed25519 \
  --purpose sign
```

**Custom Creation Date**:
```bash
# Set specific creation date (affects fingerprint!)
degen-crypto derive-pgp-key \
  --identity "user@example.com" \
  --seed "my-seed" \
  --key-type ed25519 \
  --purpose sign \
  --created-date "2024-01-01T00:00:00Z" \
  --expires-days 365
```

**Absolute Expiration Date**:
```bash
# Set specific expiration date
degen-crypto derive-pgp-key \
  --identity "user@example.com" \
  --seed "my-seed" \
  --key-type ed25519 \
  --purpose sign \
  --expires-date "2025-12-31T23:59:59Z"

# With custom creation and expiration dates
degen-crypto derive-pgp-key \
  --identity "user@example.com" \
  --seed "my-seed" \
  --key-type ed25519 \
  --purpose sign \
  --created-date "2024-06-01T00:00:00Z" \
  --expires-date "2025-06-01T00:00:00Z"
```

**PGP Validity Options**:
- `--expires-days` - Key expires N days after creation (default: never)
- `--created-date` - Creation timestamp (ISO8601 or Unix epoch). Default: 2020-01-01 for determinism
- `--expires-date` - Absolute expiration (ISO8601 or Unix epoch). Overrides `--expires-days`

**Important Notes**:
- **Default creation date is 2020-01-01 00:00:00 UTC** for deterministic fingerprints
- Changing `--created-date` will change the fingerprint (different key identity)
- For true determinism, use the default creation date
- Expiration doesn't affect the fingerprint, only the validity period
- PGP expiration is stored as days offset from creation time

#### SSH Certificates - Full Control

SSH certificates support flexible validity periods:

```bash
# Simple: Validity in days (from now)
degen-crypto derive-ssh-cert \
  --identity "alice" \
  --seed "alice-cert" \
  --cert-type user \
  --principals alice \
  --valid-days 30 \
  --ca-private-key "@ca_key"

# Advanced: Specific start and end times (ISO format)
degen-crypto derive-ssh-cert \
  --identity "server-01" \
  --seed "server-cert" \
  --cert-type host \
  --principals server-01.example.com \
  --valid-from "2024-01-01T00:00:00Z" \
  --valid-to "2024-12-31T23:59:59Z" \
  --ca-private-key "@ca_key"

# Unix timestamps also supported
degen-crypto derive-ssh-cert \
  --identity "temporary" \
  --seed "temp-cert" \
  --cert-type user \
  --principals temp-user \
  --valid-from 1704067200 \
  --valid-to 1735689599 \
  --ca-private-key "@ca_key"
```

**SSH Certificate Validity Options**:
- `--valid-days` - Certificate valid for N days from now (default: 30)
- `--valid-from` - Start of validity (ISO8601 or Unix epoch seconds)
- `--valid-to` - End of validity (ISO8601 or Unix epoch seconds)

**Common Patterns**:
```bash
# Short-lived user cert (7 days)
--cert-type user --valid-days 7

# Long-lived host cert (1 year)
--cert-type host --valid-days 365

# Cert for specific event window
--valid-from "2024-06-01T00:00:00Z" --valid-to "2024-06-07T23:59:59Z"

# Cert valid starting tomorrow
--valid-from "$(date -u -d 'tomorrow' +%Y-%m-%dT%H:%M:%SZ)" --valid-days 90
```

#### X.509 Certificates - Full Control

X.509 certificates offer the most flexible validity options:

```bash
# Simple: Validity in days (from now)
degen-crypto derive-x509 \
  --common-name "api.example.com" \
  --seed "api-cert" \
  --cert-type server \
  --validity-days 90

# Advanced: Specific validity period
degen-crypto derive-x509 \
  --common-name "secure.example.com" \
  --seed "secure-cert" \
  --cert-type server \
  --not-valid-before "2024-01-01T00:00:00Z" \
  --not-valid-after "2025-01-01T00:00:00Z"

# Unix timestamps also supported
degen-crypto derive-x509 \
  --common-name "internal-ca" \
  --seed "ca-seed" \
  --cert-type ca \
  --not-valid-before 1704067200 \
  --not-valid-after 2019513600
```

**X.509 Validity Options**:
- `--validity-days` - Certificate valid for N days from now (default: 365)
- `--not-valid-before` - Certificate valid from this time (ISO8601 or Unix epoch)
- `--not-valid-after` - Certificate expires at this time (ISO8601 or Unix epoch)

**Common Patterns**:
```bash
# Standard server cert (90 days)
--cert-type server --validity-days 90

# Long-lived CA (10 years)
--cert-type ca --validity-days 3650

# Cert with backdated start (for clock skew tolerance)
--not-valid-before "2024-01-01T00:00:00Z" \
--not-valid-after "2025-01-01T00:00:00Z"

# Cert for compliance period
--not-valid-before "$(date -u +%Y)-01-01T00:00:00Z" \
--not-valid-after "$(date -u +%Y)-12-31T23:59:59Z"
```

#### Timestamp Formats

All commands accept multiple timestamp formats:

**ISO 8601 Format** (recommended):
```bash
--valid-from "2024-06-15T14:30:00Z"           # UTC
--valid-from "2024-06-15T14:30:00+00:00"      # UTC with offset
--not-valid-before "2024-01-01T00:00:00Z"
```

**Unix Epoch Seconds**:
```bash
--valid-from 1718462400          # June 15, 2024 14:30:00 UTC
--not-valid-before 1704067200    # January 1, 2024 00:00:00 UTC
```

**Generating Timestamps**:
```bash
# Current time
date -u +%s                                  # Unix epoch
date -u +%Y-%m-%dT%H:%M:%SZ                # ISO 8601

# Specific dates
date -u -d "2024-12-31 23:59:59" +%s        # Unix epoch
date -u -d "2024-12-31 23:59:59" +%Y-%m-%dT%H:%M:%SZ  # ISO 8601

# Relative dates
date -u -d "+90 days" +%Y-%m-%dT%H:%M:%SZ   # 90 days from now
date -u -d "+1 year" +%s                     # 1 year from now
```

#### Real-World Examples

**Quarterly Certificate Rotation**:
```bash
#!/bin/bash
# Rotate certificates every quarter
YEAR=$(date +%Y)
QUARTER=$(( ($(date +%-m) - 1) / 3 + 1 ))

START_MONTH=$(( (QUARTER - 1) * 3 + 1 ))
END_MONTH=$(( QUARTER * 3 ))

degen-crypto derive-x509 \
  --common-name "quarterly.example.com" \
  --seed "quarterly-cert-$YEAR-Q$QUARTER" \
  --cert-type server \
  --not-valid-before "${YEAR}-$(printf %02d $START_MONTH)-01T00:00:00Z" \
  --not-valid-after "${YEAR}-$(printf %02d $END_MONTH)-31T23:59:59Z"
```

**SSH Certificate for Contractors**:
```bash
# 30-day contractor access
degen-crypto derive-ssh-cert \
  --identity "contractor-bob" \
  --seed "contractor-$(date +%Y%m)" \
  --cert-type user \
  --principals bob,contractor \
  --valid-days 30 \
  --extensions permit-pty \
  --ca-private-key "@company-ca.key"
```

**PGP Key for Annual Release Cycle**:
```bash
# Release signing key valid for 1 year
degen-crypto derive-pgp-identity \
  --name "Release Bot 2024" \
  --email "releases@company.com" \
  --seed "release-2024" \
  --key-type ed25519 \
  --with-subkeys \
  --expires-days 365
```

### Seed Input Methods

```bash
# From stdin
echo "my-seed" | degen-crypto derive-ssh-key ... --seed -

# From file
degen-crypto derive-ssh-key ... --seed @/path/to/seed.txt

# From environment variable
export MY_SEED="secret-seed"
degen-crypto derive-ssh-key ... --seed env:MY_SEED

# From file descriptor
degen-crypto derive-ssh-key ... --seed fd:3 3< seed.txt

# Direct string (not recommended for production)
degen-crypto derive-ssh-key ... --seed "my-seed-phrase"
```

### JSON Output Processing

```bash
# Extract specific fields
degen-crypto derive-ssh-key --seed "test" --identity "user" --pretty \
  | jq -r '.fingerprint_sha256'

# Create authorized_keys entry
degen-crypto derive-ssh-key --seed "test" --identity "deploy" \
  | jq -r '.public_key_openssh' >> ~/.ssh/authorized_keys

# Extract multiple identities
for user in alice bob carol; do
  degen-crypto derive-ssh-key \
    --seed "company-seed" \
    --identity "$user" \
    --context "ssh/users/$user" \
    | jq -r '"\(.identity): \(.fingerprint_sha256)"'
done
```

### Scripting Examples

**Generate Infrastructure Keys:**

```bash
#!/bin/bash
# generate-infra-keys.sh

SEED_FILE="/secure/infrastructure-seed.txt"
OUTPUT_DIR="./generated-keys"
mkdir -p "$OUTPUT_DIR"

# SSH keys for each environment
for env in dev staging prod; do
  degen-crypto derive-ssh-key \
    --identity "deploy@$env" \
    --seed "@$SEED_FILE" \
    --context "infrastructure/ssh/$env" \
    --key-type ed25519 \
    > "$OUTPUT_DIR/ssh-$env.json"

  echo "Generated SSH key for $env"
done

# PGP identity for release signing
degen-crypto derive-pgp-identity \
  --name "Release Bot" \
  --email "releases@company.com" \
  --seed "@$SEED_FILE" \
  --key-type ed25519 \
  --with-subkeys \
  > "$OUTPUT_DIR/pgp-release.json"

echo "Generated PGP identity for releases"
```

**Rotate Certificates:**

```bash
#!/bin/bash
# rotate-certs.sh

SEED=$(cat /secure/cert-seed.txt)
DOMAINS=("api.example.com" "web.example.com" "admin.example.com")

# Load CA
CA_CERT="@/etc/pki/ca.crt"
CA_KEY="@/etc/pki/ca.key"

for domain in "${DOMAINS[@]}"; do
  OUTPUT=$(degen-crypto derive-x509 \
    --common-name "$domain" \
    --seed "$SEED" \
    --context "tls/$domain/$(date +%Y%m)" \
    --cert-type server \
    --san "DNS:$domain,DNS:*.$domain" \
    --ca-cert "$CA_CERT" \
    --ca-key "$CA_KEY" \
    --validity-days 90)

  echo "$OUTPUT" | jq -r '.certificate_pem' > "/etc/ssl/certs/$domain.crt"
  echo "$OUTPUT" | jq -r '.private_key_pem' > "/etc/ssl/private/$domain.key"
  chmod 600 "/etc/ssl/private/$domain.key"

  echo "Rotated certificate for $domain"
done
```

---

## Security Considerations

### Seed Phrase Management

**DO:**
- ✅ Use strong, random seed phrases (256+ bits entropy)
- ✅ Store seeds in secure secret management systems (Vault, 1Password, etc.)
- ✅ Use environment variables or files, never hardcode seeds
- ✅ Monitor entropy warnings from the tool
- ✅ Use different seeds for different purposes (SSH vs PGP vs X.509)

**DON'T:**
- ❌ Use weak or guessable seeds
- ❌ Commit seeds to version control
- ❌ Share seeds across security boundaries
- ❌ Log or expose seeds in clear text

### Entropy Analysis

The tool analyzes seed phrase entropy:

```bash
# Example output showing entropy warning
{
  "metadata": {
    "seed_entropy": {
      "length": 8,
      "estimated_strength_bits": 24.5,
      "quality": "weak"  # ⚠️ WARNING
    }
  }
}
```

**Minimum Recommendations:**
- Casual use: 80+ bits (fair quality)
- Production systems: 128+ bits (good quality)
- High security: 256+ bits (excellent quality)

### Deterministic Timestamps

**PGP Keys:**
- Fixed creation timestamp: 2020-01-01 00:00:00 UTC
- Ensures reproducible fingerprints
- Does not affect cryptographic security
- May appear unusual in key servers

**X.509 Certificates:**
- Validity period starts from generation time
- Not deterministic across different runs
- Certificate fingerprints will differ

### Context Separation

Always use unique contexts when deriving multiple keys from the same seed:

```bash
# GOOD: Unique contexts
--context "ssh/production/webserver"
--context "ssh/staging/webserver"

# BAD: Same context = same key!
--context "ssh/webserver"
--context "ssh/webserver"
```

### Key Storage

```bash
# Secure file permissions
chmod 600 private_key.pem
chmod 644 public_key.pem

# Use secure directories
mkdir -p ~/.ssh && chmod 700 ~/.ssh
mkdir -p ~/.gnupg && chmod 700 ~/.gnupg
```

---

## Troubleshooting

### "Module not found" Error

```bash
# Ensure package is installed
uv pip install -e .

# Or reinstall
uv pip install -e . --force-reinstall
```

### Invalid Seed Input

```bash
# File not found
degen-crypto derive-ssh-key --seed @nonexistent.txt
# Error: File not found

# Solution: Verify file path
degen-crypto derive-ssh-key --seed @/full/path/to/seed.txt
```

### JSON Parsing Issues

```bash
# Use --pretty for readable output
degen-crypto derive-ssh-key ... --pretty | jq

# Redirect stderr if needed
degen-crypto derive-ssh-key ... 2>/dev/null | jq
```

---

## Examples Repository

For more examples, see the `examples/` directory in the repository:

```
examples/
├── infrastructure-as-code/
│   ├── terraform-ssh-keys.sh
│   └── ansible-vault-setup.sh
├── ci-cd/
│   ├── github-actions-pgp.yml
│   └── gitlab-ci-signing.yml
└── kubernetes/
    ├── tls-cert-rotation.sh
    └── service-mesh-certs.sh
```

---

## Support

- **Issues**: https://github.com/YOUR-ORG/degen-crypto/issues
- **Documentation**: https://github.com/YOUR-ORG/degen-crypto/wiki
- **Security**: security@your-domain.com

---

## License

[Your License Here]

---

**Note**: This tool is designed for deterministic key generation in controlled environments. Always follow your organization's security policies and best practices when handling cryptographic keys and certificates.
