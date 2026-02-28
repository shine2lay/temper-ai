"""Tests for temper_ai/shared/constants/durations.py."""

from temper_ai.shared.constants.durations import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_SESSION_TTL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOKEN_TTL_SECONDS,
    HOURS_PER_DAY,
    HOURS_PER_WEEK,
    MILLISECONDS_PER_SECOND,
    MINUTES_PER_HOUR,
    RATE_LIMIT_WINDOW_DAY,
    RATE_LIMIT_WINDOW_HOUR,
    RATE_LIMIT_WINDOW_MINUTE,
    RATE_LIMIT_WINDOW_SECOND,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    SECONDS_PER_MONTH_AVG,
    SECONDS_PER_WEEK,
    SECONDS_PER_YEAR,
    SLEEP_LONG,
    SLEEP_MEDIUM,
    SLEEP_SHORT,
    SLEEP_VERY_SHORT,
    TIMEOUT_DB_QUERY,
    TIMEOUT_EXTENDED,
    TIMEOUT_HTTP_DEFAULT,
    TIMEOUT_INSTANT,
    TIMEOUT_LLM_DEFAULT,
    TIMEOUT_LONG,
    TIMEOUT_MEDIUM,
    TIMEOUT_NETWORK_CONNECT,
    TIMEOUT_SHORT,
    TIMEOUT_VERY_LONG,
    TIMEOUT_VERY_SHORT,
    TTL_EXTENDED,
    TTL_LONG,
    TTL_MEDIUM,
    TTL_SHORT,
    TTL_VERY_LONG,
    TTL_VERY_SHORT,
)


class TestBasicConversions:
    def test_milliseconds_per_second(self):
        assert MILLISECONDS_PER_SECOND == 1000

    def test_seconds_per_minute(self):
        assert SECONDS_PER_MINUTE == 60

    def test_minutes_per_hour(self):
        assert MINUTES_PER_HOUR == 60

    def test_hours_per_day(self):
        assert HOURS_PER_DAY == 24

    def test_hours_per_week(self):
        assert HOURS_PER_WEEK == HOURS_PER_DAY * 7


class TestCompoundConversions:
    def test_seconds_per_hour(self):
        assert SECONDS_PER_HOUR == SECONDS_PER_MINUTE * MINUTES_PER_HOUR

    def test_seconds_per_day(self):
        assert SECONDS_PER_DAY == SECONDS_PER_HOUR * HOURS_PER_DAY

    def test_seconds_per_week(self):
        assert SECONDS_PER_WEEK == SECONDS_PER_DAY * 7

    def test_seconds_per_month(self):
        assert SECONDS_PER_MONTH_AVG == SECONDS_PER_DAY * 30

    def test_seconds_per_year(self):
        assert SECONDS_PER_YEAR == SECONDS_PER_DAY * 365


class TestTimeoutOrdering:
    def test_timeouts_increase(self):
        timeouts = [
            TIMEOUT_INSTANT,
            TIMEOUT_VERY_SHORT,
            TIMEOUT_SHORT,
            TIMEOUT_MEDIUM,
            TIMEOUT_LONG,
            TIMEOUT_VERY_LONG,
            TIMEOUT_EXTENDED,
        ]
        assert timeouts == sorted(timeouts)

    def test_all_positive(self):
        for t in [
            TIMEOUT_INSTANT,
            TIMEOUT_VERY_SHORT,
            TIMEOUT_SHORT,
            TIMEOUT_MEDIUM,
            TIMEOUT_LONG,
            TIMEOUT_VERY_LONG,
            TIMEOUT_EXTENDED,
            TIMEOUT_HTTP_DEFAULT,
            TIMEOUT_DB_QUERY,
            TIMEOUT_NETWORK_CONNECT,
            TIMEOUT_LLM_DEFAULT,
        ]:
            assert t > 0


class TestTTLOrdering:
    def test_ttls_increase(self):
        ttls = [
            TTL_VERY_SHORT,
            TTL_SHORT,
            TTL_MEDIUM,
            TTL_LONG,
            TTL_VERY_LONG,
            TTL_EXTENDED,
        ]
        assert ttls == sorted(ttls)


class TestDefaultValues:
    def test_default_timeout(self):
        assert DEFAULT_TIMEOUT_SECONDS == 1800

    def test_default_cache_ttl(self):
        assert DEFAULT_CACHE_TTL_SECONDS == 3600

    def test_default_session_ttl(self):
        assert DEFAULT_SESSION_TTL_SECONDS == 3600

    def test_default_token_ttl(self):
        assert DEFAULT_TOKEN_TTL_SECONDS == 3600


class TestRateLimitWindows:
    def test_windows_increase(self):
        windows = [
            RATE_LIMIT_WINDOW_SECOND,
            RATE_LIMIT_WINDOW_MINUTE,
            RATE_LIMIT_WINDOW_HOUR,
            RATE_LIMIT_WINDOW_DAY,
        ]
        assert windows == sorted(windows)


class TestSleepDurations:
    def test_sleep_ordering(self):
        sleeps = [SLEEP_VERY_SHORT, SLEEP_SHORT, SLEEP_MEDIUM, SLEEP_LONG]
        assert sleeps == sorted(sleeps)

    def test_all_positive(self):
        for s in [SLEEP_VERY_SHORT, SLEEP_SHORT, SLEEP_MEDIUM, SLEEP_LONG]:
            assert s > 0
