# crypto-tools

Cryptographic tools for deterministic key and certificate generation, designed for infrastructure automation.

## Features

- **Password Management**: Generate deterministic password hashes for htpasswd, Traefik, and other systems
- **SSH Key Management**: Deterministic SSH keypair generation and certificate signing
- **X.509 Certificates**: Generate deterministic X.509 keys and certificates
- **CA Bundling**: Bundle CA certificates and keys into portable JSON format

## Installation

From this project directory, use uv to install the command:

```bash
uv tool install .
degen-crypto --help
```

## Usage

Run `degen-crypto --help` to see available commands.

### Available Commands

- `derive-passwd-set` - Generate password hashes for htpasswd, Traefik, etc.
- `derive-ssh-key` - Generate SSH keypairs using optional deterministic derivation
- `derive-ssh-cert` - Generate SSH certificates with optional deterministic derivation
- `derive-x509` - Generate deterministic X.509 keys and certificates
- `bundle-ca` - Bundle CA certificate and private key into JSON format
- `bundle-ssh-ca` - Bundle SSH CA private and public keys into JSON format

## Development

### Setup

```bash
# From projects/tool.degen-crypto
# Install with development dependencies
uv sync --extra dev
```

### Testing

```bash
uv run pytest
```

## License

MIT
