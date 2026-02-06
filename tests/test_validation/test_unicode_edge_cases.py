"""Comprehensive Unicode edge case tests for security and robustness.

Tests Unicode handling in agent names, file paths, configurations, and strings
to prevent crashes, security vulnerabilities, and internationalization issues.

Covers:
- Emoji and surrogate pairs
- Zero-width characters
- RTL/bidirectional text override attacks
- Unicode normalization attacks
- Homograph attacks
- Combining characters
- Control characters in Unicode range
"""
import unicodedata

import pytest

from src.safety.validation import ValidationMixin


class TestEmojiHandling:
    """Tests for emoji in names, paths, and configs."""

    @pytest.mark.parametrize('text_with_emoji', [
        'agent-😀',  # Grinning face
        'agent-🚀',  # Rocket
        'config_📝.yaml',  # Memo
        '/path/to/📁',  # File folder
        'task-✅-complete',  # Check mark (not an emoji, but Unicode symbol)
        'agent-🔥🔥🔥',  # Multiple emojis
        '👨‍👩‍👧‍👦',  # Family emoji (multiple codepoints)
        '🏳️‍🌈',  # Rainbow flag (with ZWJ)
    ])
    def test_emoji_in_strings(self, text_with_emoji):
        """Test that emoji characters are handled correctly."""
        assert isinstance(text_with_emoji, str)
        assert len(text_with_emoji) > 0

        # Verify Unicode characters above ASCII range are preserved
        # Note: Check mark (✅) is U+2705, which is below 0x1F000
        # So we check for any non-ASCII character instead
        assert any(ord(char) > 127 for char in text_with_emoji)

    def test_emoji_grapheme_clusters(self):
        """Test emoji with multiple codepoints (grapheme clusters)."""
        # Family emoji = man + ZWJ + woman + ZWJ + girl + ZWJ + boy
        family = '👨‍👩‍👧‍👦'

        # Should be multiple codepoints
        assert len(family) > 1

        # Should contain zero-width joiners
        assert '\u200D' in family

    def test_emoji_skin_tone_modifiers(self):
        """Test emoji with skin tone modifiers."""
        base_emoji = '👋'  # Waving hand
        modified_emoji = '👋🏽'  # Waving hand: medium skin tone

        # Modified version should be longer
        assert len(modified_emoji) > len(base_emoji)

        # Both should be valid strings
        assert isinstance(base_emoji, str)
        assert isinstance(modified_emoji, str)


class TestZeroWidthCharacters:
    """Tests for zero-width characters that could be used for obfuscation."""

    @pytest.mark.parametrize('text_with_zwc', [
        ('agent\u200Bname', '\u200B'),  # Zero-width space
        ('agent\u200Cname', '\u200C'),  # Zero-width non-joiner
        ('agent\u200Dname', '\u200D'),  # Zero-width joiner
        ('agent\uFEFFname', '\uFEFF'),  # Zero-width no-break space (BOM)
        ('agent\u2060name', '\u2060'),  # Word joiner
    ])
    def test_zero_width_characters_detected(self, text_with_zwc):
        """Test detection of zero-width characters."""
        text, zwc = text_with_zwc

        # Should contain the zero-width character
        assert zwc in text

        # Visible length should differ from actual length
        visible_text = text.replace(zwc, '')
        assert len(visible_text) < len(text)

    def test_zero_width_character_at_boundaries(self):
        """Test zero-width characters at string boundaries."""
        # At start
        text_start = '\u200Bagent'
        assert text_start.startswith('\u200B')

        # At end
        text_end = 'agent\u200B'
        assert text_end.endswith('\u200B')

        # Multiple at boundaries
        text_both = '\u200Bagent\u200B'
        assert text_both.startswith('\u200B')
        assert text_both.endswith('\u200B')


class TestSurrogatePairs:
    """Tests for characters requiring surrogate pairs in UTF-16."""

    @pytest.mark.parametrize('text_with_surrogate', [
        'agent-\U0001F600',  # Grinning face (>BMP)
        'file\U0001F4C1.txt',  # File folder
        '\U0001F680rocket',  # Rocket
        'test\U00010000char',  # First char beyond BMP
        '\U0010FFFF',  # Last valid Unicode codepoint
    ])
    def test_surrogate_pair_characters(self, text_with_surrogate):
        """Test characters beyond Basic Multilingual Plane."""
        assert isinstance(text_with_surrogate, str)

        # Should contain characters with codepoint > 0xFFFF
        assert any(ord(char) > 0xFFFF for char in text_with_surrogate)

    def test_invalid_surrogate_sequences(self):
        """Test that invalid surrogate sequences are handled."""
        # Python 3 handles surrogates internally, but test encoding
        valid_text = 'test\U0001F600text'

        # Should encode to UTF-8 without issues
        encoded = valid_text.encode('utf-8')
        decoded = encoded.decode('utf-8')

        assert decoded == valid_text


class TestUnicodeNormalization:
    """Tests for Unicode normalization attacks."""

    def test_precomposed_vs_decomposed(self):
        """Test composed vs decomposed Unicode normalization."""
        # é can be represented two ways:
        precomposed = 'café'  # é as single character U+00E9
        decomposed = 'cafe\u0301'  # e + combining acute accent

        # Should look the same but be different
        assert precomposed != decomposed

        # Should normalize to same form
        assert unicodedata.normalize('NFC', precomposed) == unicodedata.normalize('NFC', decomposed)
        assert unicodedata.normalize('NFD', precomposed) == unicodedata.normalize('NFD', decomposed)

    @pytest.mark.parametrize('text_pair', [
        ('café', 'cafe\u0301'),  # é: composed vs decomposed
        ('ñ', 'n\u0303'),  # ñ: composed vs decomposed
        ('ä', 'a\u0308'),  # ä: composed vs decomposed
    ])
    def test_normalization_equivalence(self, text_pair):
        """Test that normalization makes equivalent strings equal."""
        composed, decomposed = text_pair

        # Different representations
        assert composed != decomposed

        # Same after normalization
        assert unicodedata.normalize('NFC', composed) == unicodedata.normalize('NFC', decomposed)

    def test_normalization_security_implications(self):
        """Test security implications of normalization differences."""
        # Attacker could use decomposed form to bypass filters
        normal_filename = 'résumé.pdf'
        decomposed_filename = 're\u0301sume\u0301.pdf'

        # Different as strings
        assert normal_filename != decomposed_filename

        # Could normalize to same value
        assert unicodedata.normalize('NFC', normal_filename) == unicodedata.normalize('NFC', decomposed_filename)


class TestCompatibilityNormalization:
    """Tests for NFKC/NFKD compatibility normalization attacks.

    Compatibility normalization (NFKC/NFKD) can transform visually distinct
    characters into identical ones, bypassing security filters.
    """

    @pytest.mark.parametrize('attack_pair', [
        ('\uff07', "'"),  # U+FF07 Fullwidth apostrophe → U+0027 (SQL injection bypass)
        ('\u212a', 'K'),  # U+212A Kelvin sign → U+004B Latin K (filter bypass)
        ('\u210c', 'H'),  # U+210C Black-letter H → U+0048 Latin H
        ('\u2460', '1'),  # U+2460 Circled digit one → U+0031 Digit one
        ('\ufb01', 'fi'),  # U+FB01 Latin ligature fi → U+0066 U+0069
        ('\u00b2', '2'),  # U+00B2 Superscript 2 → U+0032 Digit 2
        ('\u2075', '5'),  # U+2075 Superscript 5 → U+0035 Digit 5
    ])
    def test_nfkc_normalization_bypass(self, attack_pair):
        """Test NFKC normalization attack vectors."""
        original, expected_normalized = attack_pair

        # Should be different before normalization
        assert original != expected_normalized

        # NFKC normalization transforms to dangerous character
        result = unicodedata.normalize('NFKC', original)
        assert result == expected_normalized

    def test_fullwidth_apostrophe_sql_injection(self):
        """Test fullwidth apostrophe SQL injection bypass.

        CVE-2024-43093 exploited this: fullwidth apostrophe bypasses filters
        but normalizes to regular apostrophe, enabling SQL injection.
        """
        # Attacker input with fullwidth apostrophe
        malicious = "admin\uff07 OR 1=1--"  # U+FF07

        # Appears safe to naive filter (no ' character)
        assert "'" not in malicious

        # After NFKC normalization becomes SQL injection
        normalized = unicodedata.normalize('NFKC', malicious)
        assert "'" in normalized  # Now contains regular apostrophe
        assert "admin' OR 1=1--" == normalized

    def test_kelvin_sign_filter_bypass(self):
        """Test Kelvin sign 'Special K' polyglot attack."""
        # Kelvin sign looks like K but bypasses K-based filters
        kelvin = '\u212a'
        latin_k = 'K'

        # Different characters
        assert kelvin != latin_k
        assert ord(kelvin) != ord(latin_k)

        # But normalize to same character
        assert unicodedata.normalize('NFKC', kelvin) == latin_k

    def test_superscript_digit_normalization(self):
        """Test superscript digits normalize to regular digits."""
        superscript_123 = '\u00b9\u00b2\u00b3'  # ¹²³
        regular_123 = '123'

        # Different before normalization
        assert superscript_123 != regular_123

        # Same after NFKC normalization
        assert unicodedata.normalize('NFKC', superscript_123) == regular_123

    def test_ligature_expansion(self):
        """Test ligature characters expand to multiple characters."""
        # Latin ligature 'fi'
        ligature_fi = '\ufb01'
        regular_fi = 'fi'

        # Single character vs two characters
        assert len(ligature_fi) == 1
        assert len(regular_fi) == 2

        # Normalize to two characters
        assert unicodedata.normalize('NFKC', ligature_fi) == regular_fi


class TestHomographAttacks:
    """Tests for homograph attacks using visually similar characters."""

    @pytest.mark.parametrize('homograph_pair', [
        ('a', 'а'),  # Latin 'a' vs Cyrillic 'а' (U+0430)
        ('e', 'е'),  # Latin 'e' vs Cyrillic 'е' (U+0435)
        ('o', 'о'),  # Latin 'o' vs Cyrillic 'о' (U+043E)
        ('p', 'р'),  # Latin 'p' vs Cyrillic 'р' (U+0440)
        ('c', 'с'),  # Latin 'c' vs Cyrillic 'с' (U+0441)
    ])
    def test_homograph_character_pairs(self, homograph_pair):
        """Test detection of homograph character pairs."""
        latin, cyrillic = homograph_pair

        # Should be different codepoints
        assert ord(latin) != ord(cyrillic)

        # But might look visually identical
        assert latin != cyrillic

    def test_homograph_domain_spoofing(self):
        """Test homograph attack in domain-like strings."""
        legitimate = 'api.example.com'
        spoofed = 'аpi.example.com'  # First 'a' is Cyrillic

        # Different strings
        assert legitimate != spoofed

        # Different first character
        assert ord(legitimate[0]) != ord(spoofed[0])

        # Could be visually identical in some fonts

    def test_mixed_script_detection(self):
        """Test detection of mixed scripts (potential attack)."""
        # Mixed Latin and Cyrillic
        mixed_text = 'pay раl.com'  # 'pay' in Latin, 'раl' in Cyrillic

        # Should contain characters from different scripts
        scripts = set()
        for char in mixed_text:
            if char.isalpha():
                script_name = unicodedata.name(char, '').split()[0]
                scripts.add(script_name)

        # Verify mixed scripts detected
        assert len(scripts) >= 2, f"Expected mixed scripts, got {scripts}"
        assert 'LATIN' in scripts
        assert 'CYRILLIC' in scripts


class TestRTLAndBidiAttacks:
    """Tests for Right-to-Left and bidirectional text attacks."""

    def test_rtl_override_character(self):
        """Test RTL override character detection."""
        # RTL override can reverse display order
        normal_text = 'file.txt'
        rtl_text = 'file\u202Etxt.'  # RTL override before 'txt.'

        # Should contain RTL override
        assert '\u202E' in rtl_text

        # Codepoints are different
        assert normal_text != rtl_text

    def test_rtl_override_spoofing(self):
        """Test file extension spoofing with RTL override."""
        # Displays as "test.txt" but actually "testexe.txt" reversed
        spoofed_filename = 'test\u202Etxt.exe'

        # Should contain dangerous RTL character
        assert '\u202E' in spoofed_filename

        # Real extension is .exe
        assert spoofed_filename.endswith('exe')

    @pytest.mark.parametrize('bidi_char', [
        '\u202A',  # Left-to-Right Embedding
        '\u202B',  # Right-to-Left Embedding
        '\u202C',  # Pop Directional Formatting
        '\u202D',  # Left-to-Right Override
        '\u202E',  # Right-to-Left Override
        '\u2066',  # Left-to-Right Isolate
        '\u2067',  # Right-to-Left Isolate
        '\u2068',  # First Strong Isolate
        '\u2069',  # Pop Directional Isolate
    ])
    def test_bidirectional_control_characters(self, bidi_char):
        """Test detection of bidirectional control characters."""
        text = f'test{bidi_char}text'

        # Should contain the bidi control character
        assert bidi_char in text

        # Character should be in Format category (Cf)
        category = unicodedata.category(bidi_char)
        assert category == 'Cf', f"Expected Cf category, got {category}"


class TestCombiningCharacters:
    """Tests for combining characters and diacritical marks."""

    @pytest.mark.parametrize('base_and_combining', [
        ('e', '\u0301'),  # e + acute accent
        ('a', '\u0308'),  # a + diaeresis (umlaut)
        ('n', '\u0303'),  # n + tilde
        ('c', '\u0327'),  # c + cedilla
        ('o', '\u030A'),  # o + ring above
    ])
    def test_combining_character_attachment(self, base_and_combining):
        """Test combining characters attach to base characters."""
        base, combining = base_and_combining
        combined = base + combining

        # Should be two characters in length
        assert len(combined) == 2

        # Second character should be combining mark
        assert unicodedata.category(combining) in ['Mn', 'Mc', 'Me']

    def test_multiple_combining_characters(self):
        """Test multiple combining marks on single base."""
        # Base character with multiple diacriticals
        text = 'o\u0300\u0308'  # o + grave + diaeresis

        # Should be 3 codepoints
        assert len(text) == 3

        # Last two should be combining marks
        assert unicodedata.category(text[1]) in ['Mn', 'Mc', 'Me']
        assert unicodedata.category(text[2]) in ['Mn', 'Mc', 'Me']

    def test_combining_character_overflow(self):
        """Test excessive combining characters (potential DoS)."""
        # Zalgo text - excessive combining marks
        base = 'a'
        combining_marks = '\u0300\u0301\u0302\u0303\u0304\u0305\u0306\u0307\u0308\u0309'
        zalgo = base + combining_marks

        # Should handle without crashing
        assert isinstance(zalgo, str)
        assert len(zalgo) > len(base)


class TestControlCharactersInUnicode:
    """Tests for Unicode control characters."""

    @pytest.mark.parametrize('control_char', [
        '\u0000',  # Null
        '\u0001',  # Start of Heading
        '\u0008',  # Backspace
        '\u000B',  # Vertical Tab
        '\u000C',  # Form Feed
        '\u001B',  # Escape
        '\u007F',  # Delete
        '\u0085',  # Next Line
    ])
    def test_control_character_handling(self, control_char):
        """Test that control characters are detected."""
        text = f'test{control_char}text'

        # Should contain the control character
        assert control_char in text

        # Character should be in control category
        category = unicodedata.category(control_char)
        assert category in ['Cc', 'Cf']  # Control or Format


class TestValidationMixinUnicode:
    """Tests for ValidationMixin handling of Unicode edge cases."""

    def test_string_list_with_emoji(self):
        """Test string list validation with emoji."""
        validator = ValidationMixin()

        strings_with_emoji = ['agent-😀', 'task-🚀', 'config-📝']
        result = validator._validate_string_list(
            strings_with_emoji,
            'emoji_list',
            allow_empty=False
        )

        assert result == strings_with_emoji
        # Verify emoji preserved in each string
        assert '😀' in result[0]
        assert '🚀' in result[1]
        assert '📝' in result[2]

    def test_string_list_with_rtl_text(self):
        """Test string list validation with RTL text."""
        validator = ValidationMixin()

        # Arabic and Hebrew text
        rtl_strings = [
            'مرحبا',  # Arabic: Hello
            'שלום',   # Hebrew: Hello
            'agent-العربية'  # Mixed Latin and Arabic
        ]

        result = validator._validate_string_list(
            rtl_strings,
            'rtl_list',
            allow_empty=False
        )

        assert result == rtl_strings

    def test_string_list_excessive_length_with_unicode(self):
        """Test max length enforcement with multi-byte Unicode."""
        validator = ValidationMixin()

        # Emoji are multi-byte, so create a string with 1001 emoji characters
        long_emoji_string = '😀' * 1001  # Exceeds max_item_length=1000

        with pytest.raises(ValueError, match='exceeds maximum length'):
            validator._validate_string_list(
                [long_emoji_string],
                'long_list',
                max_item_length=1000  # Character count, not bytes
            )


class TestInternationalization:
    """Tests for international text handling."""

    @pytest.mark.parametrize('international_text', [
        '你好世界',  # Chinese: Hello World
        'こんにちは',  # Japanese: Hello
        '안녕하세요',  # Korean: Hello
        'مرحبا بالعالم',  # Arabic: Hello World
        'Здравствуй мир',  # Russian: Hello World
        'γεια σου κόσμε',  # Greek: Hello World
        'नमस्ते दुनिया',  # Hindi: Hello World
    ])
    def test_international_text_handling(self, international_text):
        """Test handling of various international scripts."""
        assert isinstance(international_text, str)
        assert len(international_text) > 0

        # Should encode to UTF-8 without issues
        encoded = international_text.encode('utf-8')
        decoded = encoded.decode('utf-8')

        assert decoded == international_text

    def test_mixed_direction_text(self):
        """Test mixed LTR and RTL text in same string."""
        mixed_text = 'Hello مرحبا World'  # English + Arabic + English

        # Should handle mixed directionality
        assert isinstance(mixed_text, str)
        assert 'Hello' in mixed_text
        assert 'مرحبا' in mixed_text
