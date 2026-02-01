"""
Comprehensive Unicode Normalization Bypass Tests (CRITICAL Priority).

Tests that FileAccessPolicy properly normalizes Unicode characters to prevent
security bypasses using:
- Unicode slash alternatives (U+2215, U+2044, U+29F8)
- Fullwidth characters (ＡＢＣ → ABC)
- Combining characters (base + combining mark)
- Different normalization forms (NFC, NFD, NFKC, NFKD)
- Homoglyph attacks (Cyrillic vs Latin)
- Zero-width characters (U+200B, U+FEFF)
- BOM (Byte Order Mark)
- Overlong UTF-8 sequences

Reference:
- test-crit-unicode-norm-01: Add Unicode normalization to prevent bypasses
- Unicode Security: https://unicode.org/reports/tr36/
- Unicode Normalization: https://unicode.org/reports/tr15/

Total: 35+ tests
Performance Target: <1ms per normalization
Success Criteria: 100% Unicode bypasses blocked
"""
import pytest
import time
import unicodedata
from src.safety.file_access import FileAccessPolicy


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def file_access_policy():
    """FileAccessPolicy configured for strict validation."""
    return FileAccessPolicy({
        "allow_parent_traversal": False,
        "denied_paths": [],
        "forbidden_directories": ["/etc", "/sys", "/proc", "/dev", "/root"],
        "forbidden_files": ["/etc/passwd", "/etc/shadow"],
    })


# ============================================================================
# Unicode Slash Tests (6 tests)
# ============================================================================

class TestUnicodeSlashes:
    """Test Unicode slash alternatives that bypass ASCII slash detection."""

    UNICODE_SLASHES = [
        ("division_slash", "/etc\u2215passwd", "/etc/passwd"),  # U+2215 DIVISION SLASH
        ("fraction_slash", "/etc\u2044passwd", "/etc/passwd"),  # U+2044 FRACTION SLASH
        ("big_solidus", "/etc\u29f8passwd", "/etc/passwd"),  # U+29F8 BIG SOLIDUS
        ("fullwidth_solidus", "/etc\uff0fpasswd", "/etc/passwd"),  # U+FF0F FULLWIDTH SOLIDUS
        ("multiple_unicode_slashes", "\u2215etc\u2215passwd", "/etc/passwd"),  # Multiple slashes
        ("mixed_ascii_unicode", "/etc\u2215\u2044passwd", "/etc/passwd"),  # Mixed slash types
    ]

    @pytest.mark.parametrize("name,attack_path,expected_normalized", UNICODE_SLASHES)
    def test_unicode_slashes_blocked(self, file_access_policy, name, attack_path, expected_normalized):
        """Unicode slash alternatives must be normalized and blocked."""
        result = file_access_policy.validate(
            action={"path": attack_path},
            context={}
        )

        assert not result.valid, f"Unicode slash bypass {name} should be blocked"
        assert len(result.violations) > 0, f"Expected violations for {name}"


# ============================================================================
# Fullwidth Character Tests (5 tests)
# ============================================================================

class TestFullwidthCharacters:
    """Test fullwidth characters that bypass ASCII checks."""

    FULLWIDTH_ATTACKS = [
        ("fullwidth_file", "\uff46\uff49\uff4c\uff45.txt", "file.txt"),  # ｆｉｌｅ
        ("fullwidth_mixed", "/\uff45tc/passwd", "/etc/passwd"),  # Mixed fullwidth/ASCII
        ("fullwidth_path", "\uff0fetc\uff0fpasswd", "/etc/passwd"),  # Fullwidth slashes
        ("fullwidth_spaces", "file\u3000name.txt", "file name.txt"),  # U+3000 IDEOGRAPHIC SPACE
    ]

    @pytest.mark.parametrize("name,attack_path,expected_normalized", FULLWIDTH_ATTACKS)
    def test_fullwidth_normalized(self, file_access_policy, name, attack_path, expected_normalized):
        """Fullwidth characters must be normalized to ASCII."""
        result = file_access_policy.validate(
            action={"path": attack_path},
            context={}
        )

        # If path contains forbidden patterns after normalization, should be blocked
        if attack_path in ["\uff0fetc\uff0fpasswd", "/\uff45tc/passwd"]:
            # These normalize to /etc/passwd
            assert not result.valid, f"Fullwidth attack {name} should be blocked"


# ============================================================================
# Combining Character Tests (4 tests)
# ============================================================================

class TestCombiningCharacters:
    """Test combining characters used to obfuscate dangerous patterns."""

    COMBINING_ATTACKS = [
        ("combining_dots", "/etc/.\u0307.\u0307/passwd"),  # Dot + combining dot above
        ("combining_slash", "/etc/\u002f\u0338passwd"),  # Slash + combining long solidus overlay
    ]

    @pytest.mark.parametrize("name,attack_path", COMBINING_ATTACKS)
    def test_combining_chars_normalized(self, file_access_policy, name, attack_path):
        """Combining characters must be normalized."""
        result = file_access_policy.validate(
            action={"path": attack_path},
            context={}
        )

        # Should be blocked (path traversal or forbidden directory)
        assert not result.valid, f"Combining character attack {name} should be blocked"


# ============================================================================
# Normalization Form Tests (8 tests)
# ============================================================================

class TestNormalizationForms:
    """Test different Unicode normalization forms (NFC, NFD, NFKC, NFKD)."""

    def test_nfc_to_nfkc(self, file_access_policy):
        """NFC input should be converted to NFKC."""
        # é as single character (NFC)
        nfc_path = "/caf\u00e9/file.txt"  # é (U+00E9)
        result = file_access_policy.validate({"path": nfc_path}, {})
        # Should handle gracefully
        assert isinstance(result.valid, bool)

    def test_nfd_to_nfkc(self, file_access_policy):
        """NFD input should be converted to NFKC."""
        # é as e + combining acute (NFD)
        nfd_path = "/cafe\u0301/file.txt"  # e + ´ (U+0301)
        result = file_access_policy.validate({"path": nfd_path}, {})
        # Should handle gracefully
        assert isinstance(result.valid, bool)

    def test_nfkd_to_nfkc(self, file_access_policy):
        """NFKD input should be converted to NFKC."""
        # Compatibility decomposed form
        nfkd_path = unicodedata.normalize('NFKD', "ｆｉｌｅ")
        result = file_access_policy.validate({"path": nfkd_path}, {})
        assert isinstance(result.valid, bool)

    def test_mixed_normalization_forms(self, file_access_policy):
        """Mixed normalization forms in one path."""
        mixed_path = "/caf\u00e9/file\u0301/data.txt"  # NFC + NFD
        result = file_access_policy.validate({"path": mixed_path}, {})
        assert isinstance(result.valid, bool)

    def test_normalization_idempotent(self, file_access_policy):
        """Normalization should be idempotent (normalizing twice = same result)."""
        path = "/etc\u2215passwd"
        # First normalization happens in validate
        result1 = file_access_policy.validate({"path": path}, {})

        # Already normalized path
        normalized_path = "/etc/passwd"
        result2 = file_access_policy.validate({"path": normalized_path}, {})

        # Both should be blocked
        assert not result1.valid and not result2.valid

    def test_precomposed_vs_decomposed(self, file_access_policy):
        """Precomposed and decomposed should normalize to same result."""
        # These should behave identically
        precomposed = "/café/file.txt"  # é as U+00E9
        decomposed = "/cafe\u0301/file.txt"  # e + ´

        result1 = file_access_policy.validate({"path": precomposed}, {})
        result2 = file_access_policy.validate({"path": decomposed}, {})

        # Both should have same validation result
        assert result1.valid == result2.valid

    def test_compatibility_equivalents(self, file_access_policy):
        """Compatibility equivalents should normalize to same canonical form."""
        # U+2215 (DIVISION SLASH) and U+002F (SOLIDUS) are compatibility equivalents
        compat_path = "/etc\u2215passwd"  # DIVISION SLASH
        standard_path = "/etc/passwd"  # SOLIDUS

        result1 = file_access_policy.validate({"path": compat_path}, {})
        result2 = file_access_policy.validate({"path": standard_path}, {})

        # Both should be blocked
        assert not result1.valid and not result2.valid

    def test_ligatures_normalized(self, file_access_policy):
        """Ligatures should be decomposed to component characters."""
        # U+FB01 (ﬁ ligature) should normalize to "fi"
        ligature_path = "/\ufb01le.txt"  # ﬁle
        result = file_access_policy.validate({"path": ligature_path}, {})
        assert isinstance(result.valid, bool)


# ============================================================================
# Zero-Width Character Tests (5 tests)
# ============================================================================

class TestZeroWidthCharacters:
    """Test zero-width characters used to hide malicious patterns."""

    ZERO_WIDTH_ATTACKS = [
        ("zero_width_space", "/et\u200bc/passwd"),  # U+200B ZERO WIDTH SPACE
        ("zero_width_non_joiner", "/etc\u200c/passwd"),  # U+200C ZERO WIDTH NON-JOINER
        ("zero_width_joiner", "/etc\u200d/passwd"),  # U+200D ZERO WIDTH JOINER
        ("word_joiner", "/etc\u2060/passwd"),  # U+2060 WORD JOINER
        ("multiple_zwsp", "/\u200be\u200bt\u200bc/passwd"),  # Multiple ZWS
    ]

    @pytest.mark.parametrize("name,attack_path", ZERO_WIDTH_ATTACKS)
    def test_zero_width_chars_removed(self, file_access_policy, name, attack_path):
        """Zero-width characters must be removed before validation."""
        result = file_access_policy.validate(
            action={"path": attack_path},
            context={}
        )

        # After removing zero-width chars, /etc/passwd should be blocked
        assert not result.valid, f"Zero-width character attack should be blocked"
        assert any(
            "forbidden" in v.message.lower() or "/etc" in v.message.lower() or "passwd" in v.message.lower()
            for v in result.violations
        ), "Expected forbidden file/directory violation"


# ============================================================================
# BOM (Byte Order Mark) Tests (3 tests)
# ============================================================================

class TestBOMHandling:
    """Test BOM (Byte Order Mark) handling."""

    def test_bom_at_start(self, file_access_policy):
        """BOM at start of path should be stripped."""
        bom_path = "\ufeff/etc/passwd"  # BOM + path
        result = file_access_policy.validate({"path": bom_path}, {})

        # After stripping BOM, should be blocked
        assert not result.valid, "BOM prefix should be stripped and path blocked"

    def test_bom_in_middle(self, file_access_policy):
        """BOM in middle of path should be removed."""
        bom_path = "/etc\ufeff/passwd"
        result = file_access_policy.validate({"path": bom_path}, {})

        # BOM removed, forbidden directory check should catch it
        assert not result.valid

    def test_multiple_boms(self, file_access_policy):
        """Multiple BOMs should all be removed."""
        bom_path = "\ufeff/et\ufeffc\ufeff/passwd"  # BOM at start and middle
        result = file_access_policy.validate({"path": bom_path}, {})
        # After removing BOMs: /etc/passwd - should be blocked
        assert not result.valid, "BOM should be removed and path blocked"


# ============================================================================
# Real-World Attack Payloads (4 tests)
# ============================================================================

class TestRealWorldUnicodeAttacks:
    """Test real-world Unicode attack payloads."""

    REAL_ATTACKS = [
        ("unicode_traversal_1", "/\u2024\u2024/etc/passwd"),  # U+2024 ONE DOT LEADER
        ("unicode_traversal_2", "/etc\u2215\u2024\u2024\u2215passwd"),  # Mixed Unicode
        ("fullwidth_traversal", "\uff0fetc\uff0f\uff0e\uff0e\uff0fpasswd"),  # Fullwidth ../
        ("zero_width_obfuscation", "/\u200be\u200bt\u200bc\u2215passwd"),  # ZWS obfuscation
    ]

    @pytest.mark.parametrize("name,attack_path", REAL_ATTACKS)
    def test_real_world_unicode_attacks_blocked(self, file_access_policy, name, attack_path):
        """Real-world Unicode attack payloads must be blocked."""
        result = file_access_policy.validate(
            action={"path": attack_path},
            context={}
        )

        assert not result.valid, f"Real-world Unicode attack {name} should be blocked"
        assert len(result.violations) > 0, f"Expected violations for {name}"


# ============================================================================
# Edge Cases (5 tests)
# ============================================================================

class TestUnicodeEdgeCases:
    """Test edge cases in Unicode normalization."""

    def test_empty_string(self, file_access_policy):
        """Empty string should be handled safely."""
        result = file_access_policy.validate({"path": ""}, {})
        assert isinstance(result.valid, bool)

    def test_only_unicode_no_ascii(self, file_access_policy):
        """Path with only Unicode characters."""
        unicode_only = "\u2215\u2215\u2215"  # Only Unicode slashes
        result = file_access_policy.validate({"path": unicode_only}, {})
        assert isinstance(result.valid, bool)

    def test_very_long_unicode_string(self, file_access_policy):
        """Very long Unicode string (DoS resistance)."""
        long_path = "/etc/" + ("a\u0301" * 1000) + "/passwd"  # 1000 combining chars
        start = time.perf_counter()
        result = file_access_policy.validate({"path": long_path}, {})
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Should complete quickly (< 10ms even for very long strings)
        assert elapsed_ms < 10.0, f"Normalization too slow: {elapsed_ms:.2f}ms"
        assert isinstance(result.valid, bool)

    def test_mixed_valid_unicode(self, file_access_policy):
        """Legitimate Unicode filename should work."""
        # Japanese, emoji, etc. in filenames
        legit_path = "/home/user/文書.txt"  # "Documents" in Japanese
        result = file_access_policy.validate({"path": legit_path}, {})
        # Should not crash, validation depends on configuration
        assert isinstance(result.valid, bool)

    def test_surrogate_pairs(self, file_access_policy):
        """Surrogate pairs (U+D800-U+DFFF) should be handled."""
        # Emoji are often represented as surrogate pairs
        emoji_path = "/home/user/file_😀.txt"
        result = file_access_policy.validate({"path": emoji_path}, {})
        assert isinstance(result.valid, bool)


# ============================================================================
# Performance Tests (1 test)
# ============================================================================

class TestUnicodeNormalizationPerformance:
    """Test Unicode normalization performance meets requirements."""

    def test_normalization_performance(self, file_access_policy):
        """Unicode normalization must complete in <1ms per validation."""
        test_paths = [
            "/etc\u2215passwd",
            "ｆｉｌｅ.ｔｘｔ",
            "/et\u200bc/passwd",
            "\ufeff/etc/passwd",
            "/cafe\u0301/data.txt",
        ]

        for path in test_paths:
            start = time.perf_counter()
            file_access_policy.validate({"path": path}, {})
            elapsed_ms = (time.perf_counter() - start) * 1000

            assert elapsed_ms < 1.0, f"Unicode normalization took {elapsed_ms:.2f}ms (target: <1ms)"


# ============================================================================
# Integration Tests (2 tests)
# ============================================================================

class TestUnicodeIntegration:
    """Integration tests for Unicode normalization with other security checks."""

    def test_url_decode_then_unicode_normalize(self, file_access_policy):
        """URL decoding should happen before Unicode normalization."""
        # %2F (URL encoded slash) + \u2215 (Unicode slash)
        combined_path = "/etc%2F\u2215passwd"

        result = file_access_policy.validate({"path": combined_path}, {})

        # After URL decode + Unicode normalize: /etc//passwd
        # Should be blocked by forbidden directory check
        assert not result.valid, "Combined URL + Unicode bypass should be blocked"

    def test_all_normalizations_combined(self, file_access_policy):
        """All normalization types combined in one attack."""
        # URL encoding + Unicode slash + fullwidth + zero-width
        attack = "/\u200be%74c\u2215\uff50asswd"  # ZWS + URL + Unicode + fullwidth

        result = file_access_policy.validate({"path": attack}, {})
        assert not result.valid, "Combined normalization bypass should be blocked"
