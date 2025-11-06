"""
Main entry point for the crypto-tools CLI.

This module serves as the entry point when running the package with:
    python -m degen_crypto
    uv run -m degen_crypto
"""

# Import the CLI and all command modules to register commands
from degen_crypto.lib_common import cli
from degen_crypto import tool_passwd  # noqa: F401
from degen_crypto import tool_ssh     # noqa: F401
from degen_crypto import tool_x509    # noqa: F401
from degen_crypto import tool_pgp     # noqa: F401


def main():
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
