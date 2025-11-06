"""
Common utilities and shared functionality for crypto-tools.

This module provides:
- CLI interface
- Shared data models
- Utility functions
- Input loading utilities

For seed derivation and entropy analysis, see lib_crypto_seed module.
"""

# Standard library imports
import sys
import os
import datetime
from typing import Literal

# Third-party imports
import click
from pydantic import BaseModel, Field

# Local imports - re-export for backwards compatibility
from degen_crypto.lib_crypto_seed import (
    EntropyAnalyzer,
    SeedDerivation,
    DeterministicRandom
)


# ============================================================================
# CLI Interface with Click
# ============================================================================

@click.group()
def cli():
    """Password and SSH Key Utilities - Deterministic derivation for infrastructure automation."""
    pass


# ============================================================================
# Utility Functions
# ============================================================================

def parse_timestamp(timestamp_str: str) -> datetime.datetime:
    """
    Parse a timestamp string to datetime object.

    Supports ISO8601 format or Unix epoch seconds.

    Args:
        timestamp_str: Timestamp as ISO8601 string or Unix epoch seconds

    Returns:
        Timezone-aware datetime object (UTC)

    Raises:
        ValueError: If timestamp cannot be parsed
    """
    # Try to parse as Unix epoch first
    try:
        epoch_seconds = float(timestamp_str)
        return datetime.datetime.fromtimestamp(epoch_seconds, tz=datetime.timezone.utc)
    except ValueError:
        pass

    # Try to parse as ISO8601
    try:
        # Try with timezone
        dt = datetime.datetime.fromisoformat(timestamp_str)
        # Ensure it's timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except ValueError:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}. Use ISO8601 or Unix epoch seconds.")


# ============================================================================
# Shared Pydantic Models
# ============================================================================

class EntropyMetrics(BaseModel):
    """Entropy analysis metrics for seed phrases."""

    length: int = Field(..., description="Length of the input string")
    shannon_entropy_bits: float = Field(..., description="Shannon entropy in bits")
    min_entropy_bits: float = Field(..., description="Min-entropy in bits")
    relative_entropy: float = Field(..., description="Relative entropy (0.0 to 1.0)")
    estimated_strength_bits: float = Field(..., description="Estimated total strength in bits")
    quality: Literal["excellent", "good", "fair", "weak", "poor", "empty"] = Field(..., description="Quality assessment")

class DerivationInfo(BaseModel):
    """Information about the derivation process."""

    method: str = Field(..., description="Derivation method used")
    iterations: int = Field(..., description="Number of iterations")
    salt_prefix: str = Field(..., description="Salt prefix used")




# ============================================================================
# CLI Input Loading Utilities
# ============================================================================

class InputLoader:
    """
    Helper utilities for loading CLI parameter values from multiple sources.

    Supports the following input prefixes:
      - ' - ' (single hyphen): read from stdin
      - '@path': read from a file path
      - 'fd:<num>': read from an open file descriptor number
      - 'env:<NAME>': read from environment variable NAME

    A leading backslash escapes special handling (e.g., '\\@file' -> '@file').
    """

    @classmethod
    def load_text(
        cls,
        value: str | None,
        *,
        description: str = "value",
        strip: bool = False
    ) -> str | None:
        """
        Load textual CLI input according to special prefixes.

        Args:
            value: Raw CLI argument (may include special prefixes or escapes)
            description: Human-readable description for error messages
            strip: Whether to strip leading/trailing whitespace from loaded text

        Returns:
            String content or None if value was None

        Raises:
            ValueError: If the referenced input cannot be loaded
        """
        if value is None:
            return None

        if value.startswith("\\"):
            loaded = value[1:]
            return loaded.strip() if strip else loaded

        if value == "-":
            loaded = sys.stdin.read()
        elif value.startswith("@"):
            path = value[1:]
            if not path:
                raise ValueError(f"Missing file path for {description}.")
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    loaded = fh.read()
            except FileNotFoundError:
                raise ValueError(f"File not found for {description}: {path}")
            except OSError as exc:
                raise ValueError(f"Error reading file for {description}: {exc}")
        elif value.startswith("fd:"):
            fd_str = value[3:]
            if not fd_str:
                raise ValueError(f"Missing file descriptor number for {description}.")
            try:
                fd = int(fd_str, 10)
            except ValueError:
                raise ValueError(f"Invalid file descriptor for {description}: {fd_str}")

            try:
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 8192)
                    if not chunk:
                        break
                    chunks.append(chunk)
                loaded = b"".join(chunks).decode("utf-8")
            except OSError as exc:
                raise ValueError(f"Error reading fd #{fd} for {description}: {exc}")
        elif value.startswith("env:"):
            env_name = value[4:]
            if not env_name:
                raise ValueError(f"Missing environment variable name for {description}.")
            try:
                loaded = os.environ[env_name]
            except KeyError:
                raise ValueError(f"Environment variable '{env_name}' not set for {description}.")
        else:
            loaded = value

        return loaded.strip() if strip else loaded
