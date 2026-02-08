"""Shannon entropy calculation for secret detection.

Provides pure entropy analysis functions reusable across multiple
security policies and threat detection systems.
"""
import math


class EntropyAnalyzer:
    """Calculate and analyze Shannon entropy of text.

    Entropy indicates randomness/uniqueness. High entropy suggests
    encrypted/random data like secrets. Low entropy suggests
    documentation or templates.

    Typical values:
    - 0.0-1.0: Very low (repetitive, like "aaaa")
    - 1.0-2.0: Low (simple patterns)
    - 2.0-3.0: Medium (mixed content)
    - 3.0-4.5: High (likely secrets)
    - 4.5-8.0: Very high (strong randomness)
    """

    @staticmethod
    def calculate(text: str) -> float:
        """Calculate Shannon entropy of text.

        Formula: H(X) = -sum(p(x) * log2(p(x))) for each unique char

        Args:
            text: Text to analyze

        Returns:
            Entropy value (0.0-8.0 bits per character)

        Examples:
            >>> EntropyAnalyzer.calculate("")
            0.0
            >>> EntropyAnalyzer.calculate("aaaaaaa")
            0.0
            >>> EntropyAnalyzer.calculate("abcdefgh")
            3.0
        """
        if not text:
            return 0.0

        # Count character frequencies
        frequencies = {}
        for char in text:
            frequencies[char] = frequencies.get(char, 0) + 1

        # Calculate entropy
        entropy = 0.0
        text_length = len(text)
        for count in frequencies.values():
            probability = count / text_length
            entropy -= probability * math.log2(probability)

        return entropy

    @staticmethod
    def is_high_entropy(text: str, threshold: float) -> bool:
        """Check if text has high entropy above threshold.

        Args:
            text: Text to analyze
            threshold: Entropy threshold (0.0-8.0)

        Returns:
            True if entropy > threshold
        """
        return EntropyAnalyzer.calculate(text) > threshold
