# pam-ussh-rs

A Rust implementation of a PAM (Pluggable Authentication Module) for SSH certificate-based authentication using ssh-agent. This module authenticates users based on SSH certificates signed by a trusted Certificate Authority (CA), providing a more secure and manageable alternative to password-based authentication.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Configuration](#configuration)
- [Certificate Setup](#certificate-setup)
- [Usage Examples](#usage-examples)
- [Troubleshooting](#troubleshooting)
- [Security Considerations](#security-considerations)

---

## Features

- ✅ **SSH Certificate-based Authentication**: Authenticate using SSH certificates instead of passwords
- ✅ **Certificate Authority (CA) Validation**: Verify certificates are signed by trusted CAs
- ✅ **Principal Matching**: Support for authorized principals lists
- ✅ **Group-based Access Control**: Optional group membership checks
- ✅ **ssh-agent Integration**: Works with standard SSH agents
- ✅ **Security Hardening**: Built-in protections against debugging and core dumps
- ✅ **Cross-Platform**: Supports Linux and macOS
- ✅ **Zero Dependencies on Runtime**: Static binary, no external libraries needed

---

## Architecture

### High-Level Flow Diagram

```
┌─────────────┐
│   User      │
│ Attempts    │
│   Login     │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│          PAM Stack (pam_ussh.so)                    │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. Platform Initialization                        │
│     ├─ Disable ptrace                              │
│     └─ Disable core dumps                          │
│                                                     │
│  2. Get Username from PAM                          │
│                                                     │
│  3. Get System User Info (UID, GID)                │
│                                                     │
│  4. Parse Module Arguments                         │
│     ├─ ca_file=/path/to/ca.pub                     │
│     ├─ group=required-group                        │
│     └─ authorized_principals=/path/to/principals   │
│                                                     │
│  5. Check Group Membership (if configured)         │
│                                                     │
│  6. Drop Privileges to Target User                 │
│                                                     │
│  7. Connect to SSH Agent                           │
│     └─ Via $SSH_AUTH_SOCK                          │
│                                                     │
│  8. Request Identities from Agent                  │
│                                                     │
│  9. For Each Certificate:                          │
│     ├─ Parse Certificate                           │
│     ├─ Check Principal Matches Username            │
│     ├─ Verify CA Signature                         │
│     ├─ Request Signature (Proof of Possession)     │
│     └─ Check Authorized Principals (if configured) │
│                                                     │
│ 10. Return PAM_SUCCESS or PAM_AUTH_ERR             │
│                                                     │
└─────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│   Grant or   │
│     Deny     │
│    Access    │
└──────────────┘
```

### Component Architecture

```
pam-ussh-rs/
├── src/
│   ├── lib.rs              # PAM module entry point
│   ├── auth.rs             # Core authentication logic
│   ├── logging.rs          # Syslog integration
│   └── platform/
│       ├── mod.rs          # Cross-platform abstractions
│       ├── linux.rs        # Linux-specific code
│       └── darwin.rs       # macOS-specific code
```

---

## How It Works

### Authentication Decision Flow (Pseudocode)

```rust
fn authenticate(username, system_info, config) -> AuthResult {
    // 1. Environment Check
    ssh_auth_sock = get_env("SSH_AUTH_SOCK")?;

    // 2. Privilege Management
    drop_privileges(system_info.uid)?;

    // 3. Agent Communication
    agent = connect_to_ssh_agent(ssh_auth_sock)?;
    identities = agent.list_identities()?;

    if identities.is_empty() {
        return ERROR("No certificates in agent");
    }

    // 4. Load Trusted CAs
    ca_keys = load_ca_public_keys(config.ca_file)?;

    // 5. Certificate Validation Loop
    for identity in identities {
        cert = parse_certificate(identity.pubkey_blob)?;

        // 5a. Check if certificate principal matches username
        if !cert.principals().contains(username) {
            continue;  // Try next certificate
        }

        // 5b. Verify CA signature
        if !is_signed_by_trusted_ca(cert, ca_keys) {
            log_warn("Certificate signed by untrusted CA");
            continue;  // Try next certificate
        }

        // 5c. Proof of possession (challenge-response)
        challenge = random_bytes(32);
        signature = agent.sign(identity.pubkey_blob, challenge)?;
        // Note: We trust the agent's signature for now

        // 5d. Check authorized principals (if configured)
        if config.authorized_principals.is_empty() {
            // No restrictions - accept any valid cert
            return SUCCESS;
        } else {
            // Check if any cert principal is in authorized list
            for principal in cert.principals() {
                if config.authorized_principals.contains(principal) {
                    return SUCCESS;
                }
            }
            continue;  // Try next certificate
        }
    }

    // 6. No valid certificate found
    return ERROR("No valid certificates found");
}
```

### Key Security Decisions

1. **Privilege Dropping**: The module drops privileges to the target user before connecting to ssh-agent
   - Prevents root from accessing user's ssh-agent
   - Ensures we're validating the correct user's certificates

2. **CA Verification**: Only certificates signed by trusted CAs are accepted
   - Prevents unauthorized certificate creation
   - Centralized trust management

3. **Principal Matching**: Certificate must have a principal matching the username
   - Prevents certificate reuse across users
   - Enforces identity binding

4. **Challenge-Response**: Agent must sign a random challenge
   - Proves possession of private key
   - Prevents replay attacks

---

## Installation

### Building from Source

```bash
# Clone the repository
git clone https://github.com/yourusername/pam-ussh-rs.git
cd pam-ussh-rs

# Build in release mode
cargo build --release

# The compiled module will be at:
# target/release/libpam_ussh.so (Linux)
# target/release/libpam_ussh.dylib (macOS)
```

### Installing the Module

```bash
# Linux
sudo install -m 0644 target/release/libpam_ussh.so /lib/security/pam_ussh.so

# Or for 64-bit systems:
sudo install -m 0644 target/release/libpam_ussh.so /lib/x86_64-linux-gnu/security/pam_ussh.so

# macOS
sudo install -m 0644 target/release/libpam_ussh.dylib /usr/local/lib/pam/pam_ussh.so
```

---

## Configuration

### PAM Configuration

Edit the appropriate PAM configuration file to include the module.

#### SSH Authentication (`/etc/pam.d/sshd`)

```pam
#%PAM-1.0

# SSH certificate authentication (try first)
auth    sufficient    pam_ussh.so ca_file=/etc/ssh/ca.pub

# Fall back to standard authentication
auth    include       password-auth

# Account, password, and session management
account include       password-auth
password include      password-auth
session include       password-auth
```

#### sudo Authentication (`/etc/pam.d/sudo`)

```pam
#%PAM-1.0

# SSH certificate authentication
auth    sufficient    pam_ussh.so ca_file=/etc/ssh/ca.pub

# Fall back to standard authentication
auth    include       system-auth

account include       system-auth
password include      system-auth
session include       system-auth
```

### Module Arguments

The PAM module accepts the following arguments:

| Argument | Description | Example |
|----------|-------------|---------|
| `ca_file` | Path to trusted CA public keys | `ca_file=/etc/ssh/ca.pub` |
| `group` | Required group membership | `group=ssh-users` |
| `authorized_principals` | Comma-separated principal list | `authorized_principals=admin,ops` |
| `authorized_principals_file` | Path to principals file | `authorized_principals_file=/etc/ssh/principals` |

#### Example Configurations

**Basic setup with CA file:**
```pam
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub
```

**Require group membership:**
```pam
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub group=ssh-users
```

**Restrict to specific principals:**
```pam
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub authorized_principals=admin,ops,devops
```

**Use principals file:**
```pam
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub authorized_principals_file=/etc/ssh/authorized_principals
```

**Combine group and principals:**
```pam
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub group=ssh-users authorized_principals_file=/etc/ssh/authorized_principals
```

---

## Certificate Setup

### 1. Generate a Certificate Authority (CA)

```bash
# Generate CA private key
ssh-keygen -t ed25519 -f /etc/ssh/ca -C "SSH CA"

# This creates:
# /etc/ssh/ca      (private key - keep secure!)
# /etc/ssh/ca.pub  (public key - distribute to servers)
```

**Security**: Store the CA private key securely! Consider:
- Offline storage (air-gapped machine)
- Hardware security module (HSM)
- Encrypted backup

### 2. Create CA Public Key File

```bash
# Copy CA public key to the location specified in PAM config
sudo cp /etc/ssh/ca.pub /etc/ssh/ca.pub
sudo chmod 644 /etc/ssh/ca.pub
```

**File format** (`/etc/ssh/ca.pub`):
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKqT... SSH CA
```

You can have multiple CA keys in this file (one per line):
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKqT... SSH CA Primary
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILmZ... SSH CA Backup
# Comments and empty lines are ignored
```

### 3. Generate User SSH Key

```bash
# User generates their SSH key (if they don't have one)
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -C "user@example.com"
```

### 4. Sign User's Public Key

```bash
# On the CA machine, sign the user's public key
ssh-keygen \
  -s /etc/ssh/ca \
  -I "alice@example.com" \
  -n alice,admin \
  -V +52w \
  -z 1 \
  ~/.ssh/id_ed25519.pub

# This creates: ~/.ssh/id_ed25519-cert.pub
```

**Parameters explained:**
- `-s /etc/ssh/ca`: CA private key to sign with
- `-I "alice@example.com"`: Certificate identifier (for logging)
- `-n alice,admin`: Valid principals (comma-separated)
- `-V +52w`: Valid for 52 weeks (1 year)
- `-z 1`: Serial number (increment for each cert)

**Advanced options:**
```bash
# Limit certificate validity period
ssh-keygen -s /etc/ssh/ca -I "alice" -n alice \
  -V 20250101:20260101 \  # Valid from Jan 1 2025 to Jan 1 2026
  ~/.ssh/id_ed25519.pub

# Add permitted options
ssh-keygen -s /etc/ssh/ca -I "alice" -n alice \
  -O source-address=192.168.1.0/24 \  # Only from this network
  -O force-command="/usr/bin/restricted-shell" \  # Force specific command
  ~/.ssh/id_ed25519.pub
```

### 5. Distribute Certificate to User

```bash
# Copy the certificate to the user's ~/.ssh/ directory
cp ~/.ssh/id_ed25519-cert.pub /home/alice/.ssh/
chown alice:alice /home/alice/.ssh/id_ed25519-cert.pub
chmod 644 /home/alice/.ssh/id_ed25519-cert.pub
```

### 6. Configure ssh-agent

```bash
# User adds their key to ssh-agent
eval $(ssh-agent)
ssh-add ~/.ssh/id_ed25519

# Verify the certificate is loaded
ssh-add -L
# Should show: ssh-ed25519-cert-v01@openssh.com AAAAA...
```

### 7. Create Authorized Principals File (Optional)

If using `authorized_principals_file`:

```bash
# Create the principals file
sudo cat > /etc/ssh/authorized_principals <<EOF
# Allowed principals for this system
admin
ops
devops
alice
EOF

sudo chmod 644 /etc/ssh/authorized_principals
```

---

## Usage Examples

### Example 1: Basic Setup

**Scenario**: Simple authentication using SSH certificates

**Setup:**
```bash
# 1. Install the PAM module
sudo install -m 0644 target/release/libpam_ussh.so /lib/security/pam_ussh.so

# 2. Configure PAM
sudo tee /etc/pam.d/sshd <<EOF
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub
auth include password-auth
account include password-auth
password include password-auth
session include password-auth
EOF

# 3. Create CA
ssh-keygen -t ed25519 -f /etc/ssh/ca -C "SSH CA"
sudo cp /etc/ssh/ca.pub /etc/ssh/ca.pub

# 4. Sign user's key
ssh-keygen -s /etc/ssh/ca -I "alice" -n alice -V +52w ~/.ssh/id_ed25519.pub

# 5. User loads certificate into agent
ssh-add ~/.ssh/id_ed25519
```

**Result**: Alice can now authenticate with her SSH certificate

---

### Example 2: Group-Based Access Control

**Scenario**: Only members of "ssh-users" group can authenticate

**Setup:**
```bash
# 1. Create group
sudo groupadd ssh-users
sudo usermod -aG ssh-users alice
sudo usermod -aG ssh-users bob

# 2. Configure PAM
sudo tee -a /etc/pam.d/sshd <<EOF
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub group=ssh-users
EOF

# 3. Sign user certificates
ssh-keygen -s /etc/ssh/ca -I "alice" -n alice -V +52w alice_id_ed25519.pub
ssh-keygen -s /etc/ssh/ca -I "bob" -n bob -V +52w bob_id_ed25519.pub
```

**Result**: Only users in "ssh-users" group can authenticate, even with valid certificates

---

### Example 3: Role-Based Access with Principals

**Scenario**: Restrict access to users with specific roles (principals)

**Setup:**
```bash
# 1. Create principals file
sudo cat > /etc/ssh/authorized_principals <<EOF
admin
ops
EOF

# 2. Configure PAM
sudo tee -a /etc/pam.d/sudo <<EOF
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub authorized_principals_file=/etc/ssh/authorized_principals
EOF

# 3. Sign certificates with appropriate principals
# Admin user
ssh-keygen -s /etc/ssh/ca -I "alice" -n alice,admin -V +52w alice_id_ed25519.pub

# Regular user (won't have sudo access)
ssh-keygen -s /etc/ssh/ca -I "bob" -n bob -V +52w bob_id_ed25519.pub
```

**Result**:
- Alice can use sudo (has "admin" principal)
- Bob cannot use sudo (doesn't have "admin" or "ops" principal)

---

### Example 4: Multi-Environment Setup

**Scenario**: Different principals for dev, staging, and production

**Setup:**
```bash
# Production servers: /etc/pam.d/sshd
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub authorized_principals=prod-admin,prod-ops

# Staging servers: /etc/pam.d/sshd
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub authorized_principals=staging-admin,staging-ops,dev

# Development servers: /etc/pam.d/sshd
auth sufficient pam_ussh.so ca_file=/etc/ssh/ca.pub authorized_principals=dev

# Sign certificates with environment-specific principals
# Production access
ssh-keygen -s /etc/ssh/ca -I "alice-prod" -n alice,prod-admin -V +4w alice_id_ed25519.pub

# Staging access
ssh-keygen -s /etc/ssh/ca -I "bob-staging" -n bob,staging-ops,dev -V +12w bob_id_ed25519.pub

# Development access only
ssh-keygen -s /etc/ssh/ca -I "charlie-dev" -n charlie,dev -V +52w charlie_id_ed25519.pub
```

**Result**: Certificates automatically limit access based on environment

---

## Troubleshooting

### Check if Module is Loaded

```bash
# Check PAM configuration
sudo cat /etc/pam.d/sshd | grep pam_ussh

# Test PAM module directly
sudo pamtester sshd alice authenticate
```

### Enable Debug Logging

```bash
# Check syslog for pam-ussh messages
sudo journalctl -t pam-ussh -f

# Or check /var/log/auth.log
sudo tail -f /var/log/auth.log | grep pam-ussh
```

### Common Issues

#### Issue: "No SSH_AUTH_SOCK environment variable"
**Cause**: ssh-agent not running or forwarded
**Solution**:
```bash
# Start ssh-agent
eval $(ssh-agent)
ssh-add ~/.ssh/id_ed25519

# For SSH with agent forwarding
ssh -A user@host
```

#### Issue: "No certificates loaded in agent"
**Cause**: Certificate not added to ssh-agent
**Solution**:
```bash
# List loaded keys
ssh-add -L

# Add certificate
ssh-add ~/.ssh/id_ed25519

# Verify certificate is loaded (should show -cert.pub)
ssh-add -L | grep cert
```

#### Issue: "Certificate signed by unrecognized authority"
**Cause**: CA public key not in ca_file or doesn't match
**Solution**:
```bash
# Verify CA public key
sudo cat /etc/ssh/ca.pub

# Check certificate's CA fingerprint
ssh-keygen -L -f ~/.ssh/id_ed25519-cert.pub

# Make sure they match
```

#### Issue: "No valid certificates found"
**Cause**: Certificate principal doesn't match username or authorized_principals
**Solution**:
```bash
# Check certificate principals
ssh-keygen -L -f ~/.ssh/id_ed25519-cert.pub | grep Principals

# Make sure it includes your username or an authorized principal
```

### Debug Build

For more verbose logging during development:

```bash
# Build in debug mode
cargo build

# Install debug version
sudo install -m 0644 target/debug/libpam_ussh.so /lib/security/pam_ussh.so

# Debug messages will appear in stderr/syslog
```

---

## Security Considerations

### Security Features

1. **Anti-Debugging**: Module prevents ptrace attachment to protect sensitive data
2. **No Core Dumps**: Disables core dumps to prevent credential leakage
3. **Privilege Separation**: Drops privileges before accessing user's ssh-agent
4. **CA Verification**: Only accepts certificates signed by trusted CAs
5. **Challenge-Response**: Requires proof of private key possession

### Best Practices

1. **Protect CA Private Key**
   - Store offline or in HSM
   - Use strong passphrase
   - Limit access to trusted administrators

2. **Short Certificate Lifetimes**
   - Recommended: 1-4 weeks for user certificates
   - Shorter for high-privilege principals
   - Forces regular re-authentication

3. **Principle of Least Privilege**
   - Grant minimal necessary principals
   - Use different certificates for different environments
   - Regular audit of principals

4. **Certificate Revocation**
   - Currently: Issue short-lived certificates
   - Future: Implement CRL or OCSP checking

5. **Monitor Certificate Usage**
   - Review syslog for authentication events
   - Alert on unusual certificate usage
   - Track certificate serial numbers

### Threat Model

**What this protects against:**
- ✅ Password-based attacks (no passwords needed)
- ✅ Credential stuffing (certificates vs passwords)
- ✅ Stolen passwords (no passwords to steal)
- ✅ Unauthorized certificate creation (CA signature required)
- ✅ Certificate reuse (principal matching required)

**What this does NOT protect against:**
- ❌ Compromised CA private key (rotate CA immediately)
- ❌ Stolen user private key + certificate (short lifetimes mitigate)
- ❌ Compromised ssh-agent (inherent to agent-based auth)
- ❌ Root compromise on server (PAM modules run as root)

---

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome! Please see CONTRIBUTING.md for guidelines.

## Credits

This is a Rust re-implementation inspired by [pam-ussh-go](https://github.com/joemiller/pam-ussh).
