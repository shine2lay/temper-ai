"""H-P3-HEALTH-EVENT: fixed pure/client fixtures, never a real host or A0 receipt.

Health success ends at the first 200. Observation elapsed ends at observed_until;
only a complete miss gives that latter pair a minimum duration. All numbers in
these new cases originate as exact decimal strings, not binary floats.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from tests.test_architecture import test_ops_host_client as fixtures

host = fixtures.host
D = Decimal

# id, first200-start, seconds_to_health, observed_until-start, elapsed, expected, reason
CASES = [
    ("qa-control", "29.999", "29.9995", "30.000", "30.0002", "PASS", None),
    ("early-health", "1.640", "1.6405", "1.641", "1.6412", "PASS", None),
    ("health-at-deadline", "30.000", "30.000", "30.001", "30.0012", "PASS", None),
    ("observation-pair-after-deadline", "29.999", "29.9995", "30.0005", "30.0005", "PASS", None),
    ("observation-band-inclusive", "29.999", "29.9995", "30.000", "30.001", "PASS", None),
    ("late-health", "30.001", "30.0015", "30.002", "30.0022", "FAIL", None),
    ("complete-miss", None, None, "30.000", "30.000", "FAIL", None),
    ("complete-miss-observation-skew", None, None, "30.000", "30.0004", "FAIL", None),
    ("complete-miss-after-deadline", None, None, "30.040", "30.040", "FAIL", None),
    ("observation-over-band", "29.999", "29.9995", "30.000", "30.0010001", "BLOCKED",
     "health_elapsed_seconds"),
    ("health-measure-crosses-deadline", "30.000", "30.0005", "30.001", "30.001", "BLOCKED",
     "seconds_to_health"),
    ("late-health-measure-crosses-deadline", "30.001", "30.000", "30.002", "30.002", "BLOCKED",
     "seconds_to_health"),
    ("miss-reported-short", None, None, "30.000", "29.9995", "BLOCKED", "not measured through"),
    ("miss-observed-short", None, None, "29.9995", "30.000", "BLOCKED", "not measured through"),
    ("miss-both-short", None, None, "29.9995", "29.9995", "BLOCKED", "not measured through"),
    ("miss-observation-over-band", None, None, "30.000", "30.0010001", "BLOCKED", "health_elapsed_seconds"),
]
PARAMS = [pytest.param(*case[1:], id=case[0]) for case in CASES]
FIELDS = ("health", "reported", "observed", "elapsed", "expected", "reason")


def at(seconds):
    """A fixed instant at an exact whole microsecond from the synthetic base."""
    micros = D(seconds) * 1_000_000
    assert micros == int(micros)
    return (fixtures.BASE + timedelta(microseconds=int(micros))).isoformat(timespec="microseconds")


def pure_case(health, reported, observed, elapsed):
    t0 = host.instant(at("0"), "start")
    first = None if health is None else D(health)
    probes = []
    s = D("0.500")
    while s < host.HEALTH_LIMIT:
        response = first is not None and s <= first <= s + D("0.600")
        end = first + D("0.001") if response else s + D("0.050")
        probe = {"_start": t0 + s, "_end": t0 + end, "result": {"status": 200 if response else None}}
        if response:
            probe["_at"] = t0 + first
        probes.append(probe)
        if response:
            break
        s += D("0.550")
    outcome = "miss" if first is None else "healthy" if first <= host.HEALTH_LIMIT else "late"
    e = {"health_at": None if first is None else at(first), "health_code": probes[-1]["result"]["status"],
         "seconds_to_health": None if reported is None else D(reported), "health_elapsed_seconds": D(elapsed),
         "health_observation": {"method": "GET", "path": "/api/items", "host": fixtures.HOST_HEADER,
                                "outcome": outcome, "probe_count": len(probes), "first_probe_at": at("0.500"),
                                "last_probe_at": at(probes[-1]["_start"] - t0), "observed_until": at(observed),
                                "elapsed_seconds": D(elapsed), "last_http_status": probes[-1]["result"]["status"],
                                "complete": True}}
    return e, probes, t0, t0 + host.HEALTH_LIMIT, t0 + D("0.400"), {"_host": fixtures.HOST_HEADER}


def apply_receipt_events(receipt, reported, observed, elapsed):
    receipt["seconds_to_health"] = None if reported is None else D(reported)
    receipt["health_elapsed_seconds"] = D(elapsed)
    until = fixtures.later(receipt["start_sent_at"], 0, us=int(D(observed) * 1_000_000))
    receipt["health_observation"].update(observed_until=until, elapsed_seconds=D(elapsed))
    if host.instant(until, "observed") > host.instant(receipt["audit_ended_at"], "audit"):
        receipt["audit_ended_at"] = until


def client_case(tmp_path, health, reported, observed, elapsed):
    """Existing client-shaped synthetic World, not a modified Ops A0 GOOD fixture."""
    w, req, raw, receipt = fixtures.build(tmp_path, "start", "D-5", "checker",
                                         {"health": None if health is None else int(D(health) * 1000)})
    apply_receipt_events(receipt, reported, observed, elapsed)
    fixtures.write_file(w.dir / "D-5.json", host._encode(receipt))
    parsed, _, _ = host.read_bound(w.dir, "D-5.json", host.RECEIPT_MAX)
    assert type(parsed["health_elapsed_seconds"]) is D
    assert parsed["health_elapsed_seconds"] == D(elapsed)
    assert parsed["health_observation"]["elapsed_seconds"] == D(elapsed)
    if reported is not None:
        assert type(parsed["seconds_to_health"]) is D and parsed["seconds_to_health"] == D(reported)
    return w, req, raw, parsed


@pytest.mark.parametrize(FIELDS, PARAMS)
def test_pure_health_events(health, reported, observed, elapsed, expected, reason):
    args = pure_case(health, reported, observed, elapsed)
    if expected == "BLOCKED":
        with pytest.raises(host.Blocked, match=reason):
            host._health(*args)
    else:
        facts = host._health(*args)
        assert facts["outcome"] == ("healthy" if expected == "PASS" else "miss" if health is None else "late")
        assert host.verdict("start", facts)[0] == expected


@pytest.mark.parametrize(FIELDS, PARAMS)
def test_client_receipt_health_events(tmp_path, health, reported, observed, elapsed, expected, reason):
    w, req, raw, receipt = client_case(tmp_path, health, reported, observed, elapsed)
    result = fixtures.judged(w, req, raw, receipt)
    assert result["status"] == expected, result["reasons"]
    assert result["sequence_valid"] is True and result["expected_sequence"] == 3
    if reason:
        assert reason in " ".join(result["reasons"]), result["reasons"]
    else:
        assert result["facts"]["outcome"] == ("healthy" if expected == "PASS" else "miss" if health is None else "late")


def test_offline_client_crash_then_start_qa_control(tmp_path):
    """Public client API with a fake file responder; no controller or host action."""
    w = fixtures.World(tmp_path)
    fixtures.seq_file(w)

    def answer(req, raw):
        if req["operation"] == "crash":
            return w.crash(req, raw)
        prior = (w.dir / "D-1.json").read_bytes()
        receipt = w.start(req, raw, prior, health=29_999)
        apply_receipt_events(receipt, "29.9995", "30.000", "30.0002")
        return host._encode(receipt)

    client, _ = fixtures.client_for(w, answer)
    crash, start = fixtures.run(client, "D-1"), fixtures.run(client, "D-5")
    assert crash["status"] == "PASS", crash["reasons"]
    assert start["status"] == "PASS", start["reasons"]
    assert start["facts"]["outcome"] == "healthy" and start["sequence"] == 2
    assert client.expected_sequence == 3 and client.crash_sha256["D-1"] == crash["receipt_sha256"]
