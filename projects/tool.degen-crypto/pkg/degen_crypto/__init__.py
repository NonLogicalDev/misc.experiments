"""
Crypto Tools - Deterministic password hash, SSH key, and X.509 certificate generation.

This package provides deterministic cryptographic material generation for
infrastructure automation, supporting:

- Password hash generation (bcrypt, APR MD5, SHA crypt, Argon2)
- SSH key generation (Ed25519, RSA, ECDSA)
- SSH certificate generation and CA management
- X.509 certificate generation and CA management

All tools support deterministic derivation from seed phrases for reproducible
Infrastructure-as-Code workflows.
"""

__version__ = "0.1.0"
