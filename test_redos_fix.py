#!/usr/bin/env python3
"""Test script to demonstrate ReDoS vulnerability and verify fix."""
import re
import time
import sys

# VULNERABLE PATTERN (original)
VULNERABLE_PATTERN = r"(?<!#)(?<!test\s)(?<!if\s)(?<!while\s)[^|]*\s*>\s*[^&>\s|]+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)"

# FIXED PATTERN (using possessive quantifiers via atomic groups)
# Python doesn't support possessive quantifiers, so we use atomic groups (?>...)
FIXED_PATTERN = r"(?<!#)(?<!test\s)(?<!if\s)(?<!while\s)(?>[^|]*?)\s*>\s*(?>[^&>\s|]+)\.(txt|json|yaml|yml|py|js|ts|md|csv|log)"

# ALTERNATIVE SIMPLIFIED PATTERN (more maintainable)
# Split the logic: detect "> file.ext" pattern, then check negative lookbehinds
SIMPLIFIED_PATTERN = r"(?<!#)(?<!test\s)(?<!if\s)(?<!while\s)\S+\s+>\s+\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)"

# BEST SOLUTION: Multiple simpler patterns
# Instead of one complex pattern, use multiple targeted patterns
TARGETED_PATTERNS = {
    "generic_redirect": r"\b\w+\s+.*?>\s*\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)",
    # Exclude comments, test, if, while via separate negative checks
}


def test_pattern(pattern_str, test_input, name="Pattern"):
    """Test a regex pattern and measure performance."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"Pattern: {pattern_str}")
    print(f"Input length: {len(test_input)}")
    print(f"Input preview: {test_input[:100]}...")

    try:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        start_time = time.time()
        match = pattern.search(test_input)
        elapsed = time.time() - start_time

        print(f"Result: {'MATCH' if match else 'NO MATCH'}")
        if match:
            print(f"Matched: {match.group(0)}")
        print(f"Time: {elapsed:.4f} seconds")

        if elapsed > 1.0:
            print("⚠️  WARNING: Potential ReDoS detected (>1s)")
            return False
        elif elapsed > 0.1:
            print("⚠️  SLOW: Pattern took >100ms")
            return False
        else:
            print("✅ FAST: Pattern completed quickly")
            return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def main():
    """Run ReDoS tests."""
    print("ReDoS Vulnerability Test")
    print("="*60)

    # Test cases
    test_cases = [
        # Normal cases (should match)
        ('echo "hello" > file.txt', True, "Simple redirect"),
        ('python script.py > output.json', True, "Script redirect"),
        ('command > results.csv', True, "Generic command redirect"),
        ('ls -la > listing.log', True, "ls redirect"),

        # Should NOT match (negative lookbehinds)
        ('# comment > file.txt', False, "Comment"),
        ('test -f > file.txt', False, "Test command"),
        ('if [ condition ] > file.txt', False, "If statement"),
        ('while read line > file.txt', False, "While loop"),

        # Piped commands (should NOT match - has pipe)
        ('command | grep pattern > file.txt', False, "Piped command"),

        # ReDoS attack vectors
        ('echo ' + 'a' * 1000 + ' >', False, "ReDoS vector 1 (1k chars)"),
        ('echo ' + 'a' * 5000 + ' >', False, "ReDoS vector 2 (5k chars)"),
        ('echo ' + 'a' * 10000 + ' >', False, "ReDoS vector 3 (10k chars)"),
        (('x' * 100) + ' > ', False, "ReDoS vector 4 (no extension)"),
        ('echo ' + ('test ' * 1000) + '>', False, "ReDoS vector 5 (repeated words)"),
    ]

    results = {
        "VULNERABLE": [],
        "FIXED": [],
        "SIMPLIFIED": []
    }

    print("\n" + "="*60)
    print("TESTING VULNERABLE PATTERN")
    print("="*60)
    for test_input, should_match, description in test_cases:
        success = test_pattern(VULNERABLE_PATTERN, test_input, f"Vulnerable: {description}")
        results["VULNERABLE"].append(success)

    print("\n" + "="*60)
    print("TESTING FIXED PATTERN (Atomic Groups)")
    print("="*60)
    for test_input, should_match, description in test_cases:
        success = test_pattern(FIXED_PATTERN, test_input, f"Fixed: {description}")
        results["FIXED"].append(success)

    print("\n" + "="*60)
    print("TESTING SIMPLIFIED PATTERN")
    print("="*60)
    for test_input, should_match, description in test_cases:
        success = test_pattern(SIMPLIFIED_PATTERN, test_input, f"Simplified: {description}")
        results["SIMPLIFIED"].append(success)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Vulnerable pattern: {sum(results['VULNERABLE'])}/{len(results['VULNERABLE'])} passed")
    print(f"Fixed pattern:      {sum(results['FIXED'])}/{len(results['FIXED'])} passed")
    print(f"Simplified pattern: {sum(results['SIMPLIFIED'])}/{len(results['SIMPLIFIED'])} passed")

    if sum(results['VULNERABLE']) < len(results['VULNERABLE']):
        print("\n⚠️  VULNERABLE PATTERN FAILED: ReDoS vulnerability confirmed")
    else:
        print("\n✅ All patterns performed well")

    return 0 if all(results['FIXED']) else 1


if __name__ == "__main__":
    sys.exit(main())
