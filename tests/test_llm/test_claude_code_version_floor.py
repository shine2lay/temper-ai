"""The Claude Code version an OAuth request claims to be.

Anthropic gates new models on a minimum CLI version and answers anything
older with 400 `claude_code_version_too_old`. Opus 5.5 moved that floor to
2.1.280; the pin sat at 2.1.260, so every 5.5 request over a subscription
token failed -- while the same model over an API key was fine, which makes
it read as a model problem rather than a header problem.

The pin will go stale again. What is worth testing is not the number but
the escape hatch: an operator hitting this at 3am must be able to fix it
with an env var, without a release. The shaper lives in gitignored
``local/``, so these skip where it is absent.
"""

import pytest

oauth = pytest.importorskip(
    "local.providers.anthropic_oauth",
    reason="local/ shaper is gitignored; present only in a working checkout",
)


class TestTheVersionFloorCanBeMovedWithoutARelease:
    def test_the_pin_is_a_bare_version(self):
        assert oauth._VERSION_RE.match(oauth.CLAUDE_CODE_VERSION)

    def test_the_pin_clears_the_floor_opus_5_5_set(self):
        """2.1.280 is the minimum Anthropic named in the 400 for Opus 5.5."""
        got = tuple(int(p) for p in oauth.CLAUDE_CODE_VERSION.split("."))
        assert got >= (2, 1, 280), f"pin {oauth.CLAUDE_CODE_VERSION} predates the Opus 5.5 floor"

    def test_an_env_override_wins_over_the_pin(self):
        assert oauth.resolve_version({oauth.VERSION_ENV: "2.9.99"}) == "2.9.99"

    def test_no_override_falls_back_to_the_pin(self):
        assert oauth.resolve_version({}) == oauth.CLAUDE_CODE_VERSION
        assert oauth.resolve_version({oauth.VERSION_ENV: "   "}) == oauth.CLAUDE_CODE_VERSION

    def test_a_malformed_override_is_refused_loudly(self):
        """A typo'd override would otherwise 400 every request with no clue why."""
        for bad in ("v2.1.280", "2.1", "latest", "2.1.280-beta"):
            with pytest.raises(ValueError, match=oauth.VERSION_ENV):
                oauth.resolve_version({oauth.VERSION_ENV: bad})
