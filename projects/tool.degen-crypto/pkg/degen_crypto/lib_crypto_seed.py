"""
Seed derivation and entropy analysis utilities.

This module provides:
- Entropy analysis for seed phrases
- Deterministic seed derivation using PBKDF2-HMAC-SHA512
- Deterministic random number generation
"""

# Standard library imports
import hashlib
import hmac
import math
from collections import Counter
from typing import Dict, Sequence
from unicodedata import normalize


# ============================================================================
# Entropy Analysis Module
# ============================================================================

class EntropyAnalyzer:
    """
    Class methods for analyzing entropy in input data.

    Provides various entropy measurements including Shannon entropy,
    relative entropy, and min-entropy for security assessment.
    """

    @classmethod
    def shannon_entropy(cls, input_data: Sequence) -> float:
        """
        Calculate Shannon entropy of input data.

        Shannon entropy measures the average amount of information contained
        in each character/byte of the input.

        Args:
            input_data: Input sequence (string, bytes, or list)

        Returns:
            Shannon entropy in bits
        """
        if not input_data:
            return 0.0

        counts = Counter(input_data)
        total = sum(counts.values())
        probs = {char: count / total for char, count in counts.items()}

        return -sum(prob * math.log2(prob) for prob in probs.values())

    @classmethod
    def relative_entropy(cls, input_data: Sequence, universe_size: int = 95) -> float:
        """
        Calculate relative entropy (normalized Shannon entropy).

        Compares actual entropy to ideal entropy for the given universe size.
        For ASCII printable characters (default), universe_size = 95.

        Args:
            input_data: Input sequence to measure
            universe_size: Size of the character universe (default: 95 for ASCII printable)

        Returns:
            Ratio of actual to ideal entropy (0.0 to 1.0)
        """
        if not input_data:
            return 0.0

        ideal_entropy = math.log2(universe_size)
        actual_entropy = cls.shannon_entropy(input_data)

        # Ratio should be between 0 and 1
        ratio = actual_entropy / ideal_entropy if ideal_entropy > 0 else 0.0

        return min(ratio, 1.0)

    @classmethod
    def min_entropy(cls, input_data: Sequence) -> float:
        """
        Calculate min-entropy (worst-case entropy).

        Min-entropy is based on the probability of the most common element.
        It represents a conservative estimate of unpredictability.

        Args:
            input_data: Input sequence to measure

        Returns:
            Min-entropy in bits
        """
        if not input_data:
            return 0.0

        counts = Counter(input_data)
        total = sum(counts.values())
        max_prob = max(counts.values()) / total

        # Min-entropy = -log2(max probability)
        return -math.log2(max_prob)

    @classmethod
    def calculate_entropy_metrics(cls, input_data: str) -> Dict:
        """
        Calculate comprehensive entropy metrics for input data.

        Args:
            input_data: Input string to analyze

        Returns:
            Dict with entropy measurements and quality assessment
        """
        if not input_data:
            return {
                "length": 0,
                "shannon_entropy_bits": 0.0,
                "min_entropy_bits": 0.0,
                "relative_entropy": 0.0,
                "estimated_strength_bits": 0.0,
                "quality": "empty"
            }

        # Calculate various entropy measures
        shannon = cls.shannon_entropy(input_data)
        min_ent = cls.min_entropy(input_data)
        rel_ent = cls.relative_entropy(input_data)

        # Estimate total entropy in the input
        estimated_total_bits = shannon * len(input_data)

        # Quality assessment based on relative entropy
        if rel_ent >= 0.8:
            quality = "excellent"
        elif rel_ent >= 0.6:
            quality = "good"
        elif rel_ent >= 0.4:
            quality = "fair"
        elif rel_ent >= 0.2:
            quality = "weak"
        else:
            quality = "poor"

        return {
            "length": len(input_data),
            "shannon_entropy_bits": round(shannon, 2),
            "min_entropy_bits": round(min_ent, 2),
            "relative_entropy": round(rel_ent, 4),
            "estimated_strength_bits": round(estimated_total_bits, 2),
            "quality": quality
        }


# ============================================================================
# Seed Derivation Module
# ============================================================================

class SeedDerivation:
    """
    Class methods for deterministic seed derivation using PBKDF2-HMAC-SHA512.

    Provides BIP39-inspired key derivation for consistent, reproducible
    cryptographic material generation.
    """

    @classmethod
    def normalize_string(cls, input_str: str, lower: bool = False) -> str:
        """
        Normalize string using Unicode NFKD normalization.

        This ensures consistent handling of Unicode characters across platforms.

        Args:
            input_str: Input string to normalize
            lower: Whether to convert to lowercase

        Returns:
            Normalized string
        """
        return normalize("NFKD", input_str.lower() if lower else input_str)

    @classmethod
    def derive_master_seed(
        cls,
        seed_phrase: str | bytes,
        salt_phrase: str | bytes = "",
        iterations: int = 2048,
        dklen: int = 64
    ) -> bytes:
        """
        Derive a master seed using PBKDF2-HMAC-SHA512 (BIP39-inspired).

        This is a unified approach for all seed derivation in this tool.
        Uses PBKDF2 with SHA512 for strong key stretching.

        Args:
            seed_phrase: User-provided seed phrase (normalized to UTF-8)
            salt_phrase: Salt phrase (normalized to UTF-8). No automatic prefix added.
            iterations: PBKDF2 iteration count (default: 2048, matching BIP39)
            dklen: Derived key length in bytes (default: 64 for SHA512)

        Returns:
            Derived seed bytes
        """
        # Normalize inputs (following BIP39 approach)
        if isinstance(seed_phrase, str):
            password_nfkd = cls.normalize_string(seed_phrase, lower=True).encode('utf-8')
        else:
            password_nfkd = seed_phrase

        if isinstance(salt_phrase, str):
            salt_nfkd = cls.normalize_string(salt_phrase).encode('utf-8')
        else:
            salt_nfkd = salt_phrase

        # Use PBKDF2-HMAC-SHA512 for key derivation
        return hashlib.pbkdf2_hmac(
            hash_name='sha512',
            password=password_nfkd,
            salt=salt_nfkd,
            iterations=iterations,
            dklen=dklen
        )

    @classmethod
    def derive_entropy_seed(
        cls,
        seed_phrase: str | bytes,
        salt_phrase: str | bytes = "",
        dklen: int = 32,
        iterations: int = 2048
    ) -> tuple[bytes, Dict]:
        """
        Derive entropy seed with metrics (unified interface).

        This function provides both the derived seed and entropy metrics
        about the input seed phrase.

        Args:
            seed_phrase: User-provided seed phrase (normalized to UTF-8)
            salt_phrase: Salt phrase (normalized to UTF-8). No automatic prefix added.
            dklen: Derived key length in bytes (default: 32)
            iterations: PBKDF2 iteration count

        Returns:
            Tuple of (seed_bytes, entropy_metrics_dict)
        """
        # Calculate entropy metrics on the input seed phrase (only for strings)
        if isinstance(seed_phrase, str):
            entropy_metrics = EntropyAnalyzer.calculate_entropy_metrics(seed_phrase)
        else:
            # For bytes input, we can't analyze character entropy
            entropy_metrics = {
                "length": len(seed_phrase),
                "shannon_entropy_bits": 0.0,
                "min_entropy_bits": 0.0,
                "relative_entropy": 0.0,
                "estimated_strength_bits": len(seed_phrase) * 8,  # Assume full byte entropy
                "quality": "unknown"
            }

        # Derive master seed using PBKDF2 with the requested dklen
        master_seed = cls.derive_master_seed(seed_phrase, salt_phrase, iterations, dklen=dklen)

        # Return the seed (no truncation needed since dklen was set correctly)
        return master_seed, entropy_metrics


# ============================================================================
# Deterministic Random Number Generator for RSA
# ============================================================================

class DeterministicRandom:
    """
    Deterministic random number generator using HMAC-SHA512.

    This class provides a deterministic source of randomness for RSA key generation.
    It uses HMAC-SHA512 with a counter to generate unlimited random bytes from a seed.
    """

    def __init__(self, seed: bytes):
        """
        Initialize the deterministic RNG with a seed.

        Args:
            seed: Seed bytes for deterministic generation
        """
        self.seed = seed
        self.counter = 0

    def read(self, n: int) -> bytes:
        """
        Read n deterministic random bytes.

        Args:
            n: Number of bytes to generate

        Returns:
            n bytes of deterministic random data
        """
        result = b""
        while len(result) < n:
            # Generate random bytes using HMAC-SHA512 with counter
            h = hmac.new(self.seed, self.counter.to_bytes(8, 'big'), hashlib.sha512)
            result += h.digest()
            self.counter += 1
        return result[:n]

    def __call__(self, n: int) -> bytes:
        """Allow callable interface for compatibility."""
        return self.read(n)
