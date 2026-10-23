"""P4 Env comparator (ABI A5, CASE F4) on fixed synthetic arrays; no host, Docker or file access.

Every F4 row has its own negative (``_n``) and clean (``_c``) test; parametrized families pair
each named field with its own clean twin. Fixtures carry a canary key and value: no result,
repr or refusal may export them, and assertions compare only results, never raw arrays, so a
failing diagnostic cannot print Env content.
"""

import ast
import dataclasses
import hashlib
import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[2] / "configs" / "architecture" / "bin"
MODULE_PATH = BIN / "ops_host_env.py"
SPEC = importlib.util.spec_from_file_location("ops_host_env", MODULE_PATH)
env = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = env
SPEC.loader.exec_module(env)

EI = "TARGET_EVIDENCE_INVALID"
CODES = (
    "TARGET_CONTEXT_MISSING",
    "TARGET_ISSUER_UNTRUSTED",
    "TARGET_PUBLICATION_INVALID",
    "TARGET_SELECTOR_MISSING",
    "TARGET_SELECTOR_AMBIGUOUS",
    "TARGET_BINDING_INVALID",
    "TARGET_SCHEMA_MISMATCH",
    "TARGET_SOURCE_MISSING",
    "TARGET_SOURCE_DRIFT",
    "TARGET_REVIEW_MISSING",
    "TARGET_EVIDENCE_INVALID",
)

SECRET_KEY = "ZZCANARYKEY"
SECRET_VAL = "zz-canary-value-7f3a"
CANARIES = (SECRET_KEY, SECRET_VAL)
PORT = 8970

# Synthetic baseline: empty value, extra '=' in a value, and the canary pair.
IMAGE = ("PATH=/usr/local/bin:/usr/bin", "LANG=C.UTF-8", "EMPTY=", "EQ=a=b==c", f"{SECRET_KEY}={SECRET_VAL}")
HOLDER_ARGV = ("python3", "/probe/probe_client.py", "hold")
CASE_ARGV = ("python3", "/app/server.py")
CASE_ENV = ("HOST=0.0.0.0", "PORT=8000", "DATA_DIR=/data", f"ALLOWED_HOSTS=100.110.162.4:{PORT},scanapp:8080")
KINDS = ("app", "forwarder", "a5-holder", "a5-case")
WINDOW_KINDS = ("app", "forwarder")
A5_KINDS = ("a5-holder", "a5-case")

CLEAN = env.EnvAssessment("UNTRUSTED", True, True, "NONE")
VALUE_FALSE = env.EnvAssessment("UNTRUSTED", False, True, "ENV_VALUE")
DUPLICATE_FALSE = env.EnvAssessment("UNTRUSTED", False, True, "ENV_DUPLICATE")
ORDER_FALSE = env.EnvAssessment("UNTRUSTED", False, False, "ENV_ORDER")
MAX = env.MAX_ARRAY_BYTES


def app_tokens(port=PORT):
    return ("HOST=0.0.0.0", "PORT=8000", "DATA_DIR=/data", f"ALLOWED_HOSTS=100.110.162.4:{port},scanapp:8080")


def container(kind, image=IMAGE, port=PORT):
    """The expected full container array for a kind: baseline plus that kind's overrides."""
    if kind == "app":
        return image + app_tokens(port)
    if kind == "a5-case":
        return image + CASE_ENV
    return image


def run(kind, image, creation, observed, port=PORT):
    if kind in WINDOW_KINDS:
        return env.compare_window_env(image, creation, observed, target=kind, port=port)
    argv, recipe = (HOLDER_ARGV, ()) if kind == "a5-holder" else (CASE_ARGV, CASE_ENV)
    return env.compare_a5_env(image, creation, observed, expected_argv=argv, observed_argv=argv, expected_env=recipe)


def case(image=IMAGE, creation=None, observed=None, *, argv=CASE_ARGV, observed_argv=CASE_ARGV, recipe=CASE_ENV):
    creation = image + recipe if creation is None else creation
    observed = creation if observed is None else observed
    return env.compare_a5_env(image, creation, observed, expected_argv=argv, observed_argv=observed_argv, expected_env=recipe)


def exported_text(obj):
    """Everything a result or refusal exports: repr, str, fields, args, notes and chain."""
    parts = [repr(obj), str(obj)]
    if isinstance(obj, BaseException):
        parts += [repr(arg) for arg in obj.args]
        parts += [repr(note) for note in getattr(obj, "__notes__", ())]
        parts.append(repr(getattr(obj, "__dict__", {})))
        for linked in (obj.__cause__, obj.__context__):
            if linked is not None:
                parts.append(exported_text(linked))
    elif dataclasses.is_dataclass(obj):
        parts += [repr(dataclasses.astuple(obj)), repr(dataclasses.asdict(obj))]
    return "\n".join(parts)


def leaks(obj):
    text = exported_text(obj)
    return any(canary in text for canary in CANARIES)


def refusal(call):
    """Run a call that must refuse; return the exact local refusal after checking its shape."""
    with pytest.raises(env.TargetRefused) as info:
        call()
    exc = info.value
    shape = (type(exc) is env.TargetRefused, exc.args == (EI,), str(exc) == EI, exc.code == EI,
             exc.__cause__ is None, exc.__context__ is None, leaks(exc))
    assert shape == (True, True, True, True, True, True, False), "refusal shape"
    return exc


def without(tokens, key):
    return tuple(token for token in tokens if token.partition("=")[0] != key)


def replaced(tokens, key, token):
    return tuple(token if item.partition("=")[0] == key else item for item in tokens)


# ---------------------------------------------------------------- F4-IMAGE-ABSENT (P4-05)

class TupleSub(tuple):
    pass


class StrSub(str):
    pass


IMAGE_ABSENT = [
    pytest.param(None, id="none"),
    pytest.param(list(IMAGE), id="list"),
    pytest.param([], id="empty-list"),
    pytest.param("\n".join(IMAGE), id="joined-string"),
    pytest.param(dict(token.split("=", 1) for token in IMAGE), id="map"),
    pytest.param(frozenset(IMAGE), id="set"),
    pytest.param(TupleSub(IMAGE), id="tuple-subclass"),
    pytest.param((b"PATH=/bin",), id="bytes-item"),
    pytest.param((1,), id="int-item"),
    pytest.param((None,), id="none-item"),
    pytest.param((StrSub("PATH=/bin"),), id="str-subclass-item"),
    pytest.param(("",), id="empty-item"),
    pytest.param(("BAD=\ud800",), id="invalid-utf8"),
    pytest.param((f"BIG={'x' * (MAX - 3)}",), id="over-byte-bound"),
    pytest.param(("A=",) * (MAX + 1), id="over-count-bound"),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("image", IMAGE_ABSENT)
def test_f4_image_absent_n(kind, image):
    good = container(kind)
    refusal(lambda: run(kind, image, good, good))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("image", [pytest.param(IMAGE, id="full"), pytest.param((), id="explicit-empty")])
def test_f4_image_absent_c(kind, image):
    good = container(kind, image)
    result = run(kind, image, good, good)
    assert result == CLEAN


@pytest.mark.parametrize("kind", ("forwarder", "a5-holder"))
def test_f4_image_absent_c_at_byte_bound(kind):
    image = (f"BIG={'x' * (MAX - 4)}",)
    result = run(kind, image, image, image)
    assert result == CLEAN


def test_f4_image_absent_n_missing_argument_is_no_default():
    with pytest.raises(TypeError):
        env.compare_window_env(creation_env=IMAGE, observed_env=IMAGE, target="forwarder", port=PORT)
    with pytest.raises(TypeError):
        env.compare_a5_env(creation_env=IMAGE, observed_env=IMAGE, expected_argv=HOLDER_ARGV,
                           observed_argv=HOLDER_ARGV, expected_env=())


# ---------------------------------------------------------------- F4-IMAGE-DUP (P4-05)

IMAGE_DUP = [
    pytest.param(("A=1", "A=1"), ("A=1",), id="identical"),
    pytest.param(("A=1", "A=2"), ("A=1", "B=2"), id="last-wins-would-hide"),
    pytest.param(IMAGE + (IMAGE[0],), IMAGE, id="repeat-in-full-baseline"),
    pytest.param(("A=", "A="), ("A=",), id="empty-values"),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(("dup", "unique"), IMAGE_DUP)
def test_f4_image_dup_n(kind, dup, unique):
    good = container(kind, unique)
    refusal(lambda: run(kind, dup, good, good))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(("dup", "unique"), IMAGE_DUP)
def test_f4_image_dup_c(kind, dup, unique):
    good = container(kind, unique)
    result = run(kind, unique, good, good)
    assert result == CLEAN


# ---------------------------------------------------------------- F4-TOKEN (P4-01..03)

TOKENS = [
    pytest.param("NOEQUALS", "NOEQUALS=", id="missing-equals"),
    pytest.param("=value", "K=value", id="empty-key"),
    pytest.param("=", "K=", id="only-equals"),
    pytest.param("K\x00EY=v", "KEY=v", id="nul-in-key"),
    pytest.param("K=v\x00x", "K=vx", id="nul-in-value"),
    pytest.param("", "K=", id="empty-token"),
]
POSITIONS = ("image", "creation", "observed")


def token_arrays(kind, token, good, position):
    """Arrays with ``good`` in the baseline and both containers, then ``token`` at one position."""
    image = IMAGE + (good,)
    creation = observed = container(kind, image)
    if position == "image":
        image = IMAGE + (token,)
    elif position == "creation":
        creation = replaced(creation, good.partition("=")[0], token)
    else:
        observed = replaced(observed, good.partition("=")[0], token)
    return image, creation, observed


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize(("bad", "good"), TOKENS)
def test_f4_token_n(kind, position, bad, good):
    arrays = token_arrays(kind, bad, good, position)
    refusal(lambda: run(kind, *arrays))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize(("bad", "good"), TOKENS)
def test_f4_token_c(kind, position, bad, good):
    arrays = token_arrays(kind, good, good, position)
    result = run(kind, *arrays)
    assert result == CLEAN


VALUE_CHANGES = [
    pytest.param("EQ", "EQ=a=b=c", id="extra-equals-resplit"),
    pytest.param("EQ", "EQ=a", id="value-cut-at-second-equals"),
    pytest.param("EMPTY", "EMPTY= ", id="empty-value-padded"),
    pytest.param("LANG", "LANG=c.utf-8", id="value-case-folded"),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(("key", "token"), VALUE_CHANGES)
def test_f4_token_n_value_not_resplit_or_normalized(kind, key, token):
    changed = replaced(container(kind), key, token)
    result = run(kind, IMAGE, changed, changed)
    assert result == VALUE_FALSE


@pytest.mark.parametrize("kind", KINDS)
def test_f4_token_c_empty_and_extra_equals_values_kept_exactly(kind):
    good = container(kind)
    result = run(kind, IMAGE, good, good)
    kept = "EMPTY=" in good and "EQ=a=b==c" in good
    assert result == CLEAN
    assert kept is True


# ---------------------------------------------------------------- F4-APP-OVERRIDES (P4-07)

APP_WRONG = [
    pytest.param("HOST", "HOST=127.0.0.1", id="host-wrong"),
    pytest.param("PORT", f"PORT={PORT}", id="port-wrong"),
    pytest.param("DATA_DIR", "DATA_DIR=/data/", id="data-dir-wrong"),
    pytest.param("ALLOWED_HOSTS", f"ALLOWED_HOSTS=100.110.162.4:{PORT + 1},scanapp:8080", id="allowed-hosts-port-wrong"),
    pytest.param("ALLOWED_HOSTS", f"ALLOWED_HOSTS=100.110.162.4:{PORT}", id="allowed-hosts-scanapp-missing"),
    pytest.param("HOST", None, id="host-missing"),
    pytest.param("PORT", None, id="port-missing"),
    pytest.param("DATA_DIR", None, id="data-dir-missing"),
    pytest.param("ALLOWED_HOSTS", None, id="allowed-hosts-missing"),
]


@pytest.mark.parametrize(("key", "token"), APP_WRONG)
def test_f4_app_overrides_n(key, token):
    good = container("app")
    bad = without(good, key) if token is None else replaced(good, key, token)
    result = run("app", IMAGE, bad, bad)
    assert result == VALUE_FALSE


@pytest.mark.parametrize(("key", "token"), APP_WRONG)
def test_f4_app_overrides_c(key, token):
    good = container("app")
    exact = dict(item.split("=", 1) for item in app_tokens())
    result = run("app", IMAGE, good, good)
    assert result == CLEAN
    assert (key in exact, set(exact) == set(env.APP_KEYS)) == (True, True)


def test_f4_app_overrides_n_fifth_override():
    bad = container("app") + ("EXTRA_OVERRIDE=1",)
    result = run("app", IMAGE, bad, bad)
    assert result == VALUE_FALSE


def test_f4_app_overrides_c_image_key_replaced_by_override():
    image = IMAGE + ("HOST=127.0.0.1",)
    good = IMAGE + app_tokens()
    kept = image + app_tokens()[1:]
    assert run("app", image, good, good) == CLEAN
    assert run("app", image, kept, kept) == VALUE_FALSE


# ---------------------------------------------------------------- F4-INHERITED (P4-07, P4-08)

INHERITED = [
    pytest.param("PATH", None, id="path-lost"),
    pytest.param("EMPTY", None, id="empty-value-key-lost"),
    pytest.param(SECRET_KEY, None, id="canary-key-lost"),
    pytest.param("LANG", "LANG=en_US.UTF-8", id="lang-changed"),
    pytest.param("EQ", "EQ=a=b", id="extra-equals-value-changed"),
    pytest.param("PATH", "PATH=/usr/bin", id="path-changed"),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(("key", "token"), INHERITED)
def test_f4_inherited_n(kind, key, token):
    good = container(kind)
    bad = without(good, key) if token is None else replaced(good, key, token)
    result = run(kind, IMAGE, bad, bad)
    assert result == VALUE_FALSE
    assert leaks(result) is False


@pytest.mark.parametrize("kind", KINDS)
def test_f4_inherited_n_extra_key(kind):
    bad = container(kind) + ("NOT_IN_IMAGE=1",)
    result = run(kind, IMAGE, bad, bad)
    assert result == VALUE_FALSE


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(("key", "token"), INHERITED)
def test_f4_inherited_c(kind, key, token):
    good = container(kind)
    result = run(kind, IMAGE, good, good)
    present = any(item.partition("=")[0] == key for item in good)
    assert result == CLEAN
    assert present is True


# ---------------------------------------------------------------- F4-FORWARDER (P4-08)

FORWARDER_OVERRIDES = [pytest.param(app_tokens(), id="all-four")] + [
    pytest.param((token,), id=token.partition("=")[0].lower().replace("_", "-")) for token in app_tokens()
]


@pytest.mark.parametrize("overrides", FORWARDER_OVERRIDES)
def test_f4_forwarder_n(overrides):
    bad = IMAGE + overrides
    result = run("forwarder", IMAGE, bad, bad)
    assert result == VALUE_FALSE


def test_f4_forwarder_n_app_without_overrides():
    result = run("app", IMAGE, IMAGE, IMAGE)
    assert result == VALUE_FALSE


@pytest.mark.parametrize("overrides", FORWARDER_OVERRIDES)
def test_f4_forwarder_c(overrides):
    result = run("forwarder", IMAGE, IMAGE, IMAGE)
    assert result == CLEAN


# ---------------------------------------------------------------- F4-DUPLICATE (P4-04, P4-06)

def duplicate_arrays(kind, variant):
    good = container(kind)
    if variant == "last-wins-would-hide":
        return ("PATH=/evil",) + good, None
    if variant == "first-wins-would-hide":
        return good + ("PATH=/evil",), None
    if variant == "identical-repeat":
        return good + (good[0],), None
    if variant == "tail-repeat":  # for app: the ALLOWED_HOSTS override token
        return good + (good[-1],), None
    return good, good + (good[0],)  # observed-only


DUPLICATES = ("last-wins-would-hide", "first-wins-would-hide", "identical-repeat", "tail-repeat", "observed-only")


@pytest.mark.parametrize("kind", WINDOW_KINDS)
@pytest.mark.parametrize("variant", DUPLICATES)
def test_f4_duplicate_n(kind, variant):
    creation, observed = duplicate_arrays(kind, variant)
    later = creation if observed is None else observed
    result = run(kind, IMAGE, creation, later)
    expected = DUPLICATE_FALSE if observed is None else env.EnvAssessment("UNTRUSTED", False, False, "ENV_DUPLICATE")
    assert result == expected


@pytest.mark.parametrize("kind", WINDOW_KINDS)
@pytest.mark.parametrize("variant", DUPLICATES)
def test_f4_duplicate_c(kind, variant):
    good = container(kind)
    result = run(kind, IMAGE, good, good)
    unique = len({item.partition("=")[0] for item in good}) == len(good)
    assert result == CLEAN
    assert unique is True


# ---------------------------------------------------------------- F4-ORDER (P4-11)

def swapped(tokens):
    return (tokens[1], tokens[0]) + tokens[2:]


ORDERS = [pytest.param(swapped, id="adjacent-swap"), pytest.param(lambda t: tuple(reversed(t)), id="reversed")]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("drift", ORDERS)
def test_f4_order_n(kind, drift):
    creation = container(kind)
    result = run(kind, IMAGE, creation, drift(creation))
    assert result == ORDER_FALSE


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("drift", ORDERS)
def test_f4_order_c(kind, drift):
    creation = container(kind)
    result = run(kind, IMAGE, creation, tuple(creation))
    assert result == CLEAN


@pytest.mark.parametrize("kind", KINDS)
def test_f4_order_c_initial_map_invents_no_order(kind):
    creation = tuple(reversed(container(kind)))
    result = run(kind, IMAGE, creation, creation)
    assert result == CLEAN


# ---------------------------------------------------------------- F4-IMAGE-ORDER (P4-11)

ORDER_LOSING = [
    pytest.param(lambda t: dict(item.split("=", 1) for item in t), id="map"),
    pytest.param(frozenset, id="set"),
    pytest.param(sorted, id="sorted-list"),
]


@pytest.mark.parametrize("kind", KINDS)
def test_f4_image_order_n(kind):
    first, second = IMAGE, tuple(reversed(IMAGE))
    copies = (tuple(first), tuple(second))
    good = container(kind)
    results = (run(kind, first, good, good), run(kind, second, good, good))
    # Same content, different order: P4 neither rejects it by inventing an order nor erases
    # it; the caller's arrays stay distinct and unchanged for P5's own ordered equality.
    kept_distinct = first == copies[0] and second == copies[1] and first != second
    assert results == (CLEAN, CLEAN)
    assert kept_distinct is True
    assert [field.name for field in dataclasses.fields(results[0])] == ["trust", "env_matches", "creation_matches", "reason"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("lose", ORDER_LOSING)
def test_f4_image_order_n_order_losing_baseline_refused(kind, lose):
    good = container(kind)
    refusal(lambda: run(kind, lose(IMAGE), good, good))


@pytest.mark.parametrize("kind", KINDS)
def test_f4_image_order_c(kind):
    first, second = IMAGE, tuple(IMAGE)
    good = container(kind)
    results = (run(kind, first, good, good), run(kind, second, good, good))
    identical = first == second
    assert results == (CLEAN, CLEAN)
    assert identical is True


# ---------------------------------------------------------------- F4-A5-KEYS (P4-10)

A5_BAD_KEYS = [
    pytest.param("1BAD=x", "B1AD=x", id="leading-digit"),
    pytest.param("BAD-KEY=x", "BAD_KEY=x", id="hyphen"),
    pytest.param("BAD.KEY=x", "BADKEY=x", id="dot"),
    pytest.param("BAD KEY=x", "BADKEY2=x", id="space"),
    pytest.param(" LEAD=x", "LEAD=x", id="leading-space"),
    pytest.param("\u00c4KEY=x", "AKEY=x", id="non-ascii"),
    pytest.param("KEY\n=x", "KEY3=x", id="trailing-newline"),
]
A5_LOCATIONS = ("image", "creation", "observed", "expected_env")


def a5_arrays(token, location):
    """Case arrays with a valid extra key, then ``token`` placed at one location."""
    image, recipe = IMAGE, CASE_ENV
    if location == "expected_env":
        recipe = CASE_ENV + (token,)
        creation = observed = IMAGE + CASE_ENV + (token,)
    else:
        image = IMAGE + (token,)
        creation = observed = image + CASE_ENV
    return image, creation, observed, recipe


def a5_call(arrays):
    image, creation, observed, recipe = arrays
    return case(image, creation, observed, recipe=recipe)


@pytest.mark.parametrize("location", A5_LOCATIONS)
@pytest.mark.parametrize(("bad", "good"), A5_BAD_KEYS)
def test_f4_a5_keys_n_regex(location, bad, good):
    image, creation, observed, recipe = a5_arrays(good, location)
    if location == "image":
        image = IMAGE + (bad,)
    elif location == "creation":
        creation = replaced(creation, good.partition("=")[0], bad)
    elif location == "observed":
        observed = replaced(observed, good.partition("=")[0], bad)
    else:
        recipe = replaced(recipe, good.partition("=")[0], bad)
    refusal(lambda: a5_call((image, creation, observed, recipe)))


@pytest.mark.parametrize("location", A5_LOCATIONS)
@pytest.mark.parametrize(("bad", "good"), A5_BAD_KEYS)
def test_f4_a5_keys_c_regex(location, bad, good):
    result = a5_call(a5_arrays(good, location))
    assert result == CLEAN


APP_KEY_TOKENS = [
    pytest.param("HOST=x", "HOSTNAME=x", id="host"),
    pytest.param("PORT=x", "PORTS=x", id="port"),
    pytest.param("DATA_DIR=x", "DATA_DIRS=x", id="data-dir"),
    pytest.param("ALLOWED_HOSTS=x", "ALLOWED_HOST=x", id="allowed-hosts"),
]


@pytest.mark.parametrize("kind", A5_KINDS)
@pytest.mark.parametrize(("bad", "good"), APP_KEY_TOKENS)
def test_f4_a5_keys_n_app_key_in_baseline(kind, bad, good):
    image = IMAGE + (bad,)
    good_container = container(kind, image)
    refusal(lambda: run(kind, image, good_container, good_container))


@pytest.mark.parametrize("kind", A5_KINDS)
@pytest.mark.parametrize(("bad", "good"), APP_KEY_TOKENS)
def test_f4_a5_keys_c_app_key_absent(kind, bad, good):
    image = IMAGE + (good,)
    good_container = container(kind, image)
    result = run(kind, image, good_container, good_container)
    assert result == CLEAN


A5_DUP_LOCATIONS = ("image", "creation", "observed", "expected_env")


def a5_duplicate(location):
    image, creation, observed, recipe = IMAGE, IMAGE + CASE_ENV, IMAGE + CASE_ENV, CASE_ENV
    if location == "image":
        image = IMAGE + (IMAGE[0],)
    elif location == "creation":
        creation = creation + (creation[0],)
    elif location == "observed":
        observed = observed + (observed[0],)
    else:
        recipe = CASE_ENV + (CASE_ENV[0],)
    return image, creation, observed, recipe


@pytest.mark.parametrize("location", A5_DUP_LOCATIONS)
def test_f4_a5_keys_n_duplicate(location):
    arrays = a5_duplicate(location)
    refusal(lambda: a5_call(arrays))


@pytest.mark.parametrize("location", A5_DUP_LOCATIONS)
def test_f4_a5_keys_c_unique(location):
    result = a5_call((IMAGE, IMAGE + CASE_ENV, IMAGE + CASE_ENV, CASE_ENV))
    assert result == CLEAN


GENERIC_WINDOW_KEYS = [pytest.param(bad, id=f"window-{name}") for (bad, _), name in zip(
    [p.values for p in A5_BAD_KEYS], [p.id for p in A5_BAD_KEYS], strict=True)]


@pytest.mark.parametrize("kind", WINDOW_KINDS)
@pytest.mark.parametrize("token", GENERIC_WINDOW_KEYS)
def test_f4_a5_keys_c_window_keeps_generic_grammar(kind, token):
    # The A5 regex does not replace the generic window grammar (P4-02, P4-10).
    image = IMAGE + (token,)
    good = container(kind, image)
    result = run(kind, image, good, good)
    assert result == CLEAN


# ---------------------------------------------------------------- F4-A5-RECIPE (P4-12)

RECIPE_DIFF = [
    pytest.param({"observed_argv": CASE_ARGV + ("--debug",)}, id="argv-extra"),
    pytest.param({"observed_argv": CASE_ARGV[:1]}, id="argv-missing"),
    pytest.param({"observed_argv": ("python3", "/app/other.py")}, id="argv-different"),
    pytest.param({"observed_argv": tuple(reversed(CASE_ARGV))}, id="argv-reordered"),
    pytest.param({"observed_argv": ()}, id="argv-empty"),
    pytest.param({"creation": IMAGE + replaced(CASE_ENV, "HOST", "HOST=127.0.0.1")}, id="env-value-wrong"),
    pytest.param({"creation": IMAGE + without(CASE_ENV, "DATA_DIR")}, id="env-key-missing"),
    pytest.param({"creation": IMAGE + CASE_ENV + ("EXTRA=1",)}, id="env-key-extra"),
    pytest.param({"creation": without(IMAGE, "LANG") + CASE_ENV}, id="env-inherited-lost"),
]


@pytest.mark.parametrize("change", RECIPE_DIFF)
def test_f4_a5_recipe_n(change):
    result = case(**change)
    assert result == VALUE_FALSE


def test_f4_a5_recipe_n_holder_given_case_env():
    result = env.compare_a5_env(IMAGE, IMAGE + CASE_ENV, IMAGE + CASE_ENV, expected_argv=HOLDER_ARGV,
                                observed_argv=HOLDER_ARGV, expected_env=())
    assert result == VALUE_FALSE


@pytest.mark.parametrize("change", RECIPE_DIFF)
def test_f4_a5_recipe_c(change):
    assert case() == CLEAN
    holder = env.compare_a5_env(IMAGE, IMAGE, IMAGE, expected_argv=HOLDER_ARGV, observed_argv=HOLDER_ARGV,
                                expected_env=())
    assert holder == CLEAN


RECIPE_MALFORMED = [
    pytest.param({"argv": ()}, id="expected-argv-empty"),
    pytest.param({"argv": None}, id="expected-argv-none"),
    pytest.param({"argv": list(CASE_ARGV)}, id="expected-argv-list"),
    pytest.param({"argv": ("python3", "")}, id="expected-argv-empty-item"),
    pytest.param({"argv": ("python3", "/app/server.py\x00")}, id="expected-argv-nul"),
    pytest.param({"observed_argv": None}, id="observed-argv-none"),
    pytest.param({"observed_argv": list(CASE_ARGV)}, id="observed-argv-list"),
    pytest.param({"observed_argv": ("python3", 1)}, id="observed-argv-int-item"),
    pytest.param({"recipe": None}, id="expected-env-none"),
    pytest.param({"recipe": list(CASE_ENV)}, id="expected-env-list"),
    pytest.param({"recipe": ("HOST",)}, id="expected-env-token-no-equals"),
]


@pytest.mark.parametrize("change", RECIPE_MALFORMED)
def test_f4_a5_recipe_n_malformed_mandatory_data(change):
    refusal(lambda: case(creation=IMAGE + CASE_ENV, **change))


@pytest.mark.parametrize("change", RECIPE_MALFORMED)
def test_f4_a5_recipe_c_exact_mandatory_data(change):
    result = env.compare_a5_env(IMAGE, IMAGE + CASE_ENV, IMAGE + CASE_ENV, expected_argv=CASE_ARGV,
                                observed_argv=CASE_ARGV, expected_env=CASE_ENV)
    assert result == CLEAN


# ---------------------------------------------------------------- F4-PORT (P4-09)

class IntSub(int):
    pass


BAD_PORTS = [
    pytest.param(True, id="bool-true"),
    pytest.param(False, id="bool-false"),
    pytest.param(0, id="zero"),
    pytest.param(-1, id="negative"),
    pytest.param(65536, id="above-range"),
    pytest.param(8970.0, id="float"),
    pytest.param("8970", id="string"),
    pytest.param(None, id="none"),
    pytest.param(IntSub(8970), id="int-subclass"),
]


@pytest.mark.parametrize("kind", WINDOW_KINDS)
@pytest.mark.parametrize("port", BAD_PORTS)
def test_f4_port_n(kind, port):
    good = container(kind)
    refusal(lambda: env.compare_window_env(IMAGE, good, good, target=kind, port=port))


@pytest.mark.parametrize("kind", WINDOW_KINDS)
@pytest.mark.parametrize("port", [1, 80, 8970, 8979, 65535])
def test_f4_port_c(kind, port):
    # Any actual integer 1..65535 is data here; the narrower 8970..8979 window check is P5's.
    good = container(kind, port=port)
    result = run(kind, IMAGE, good, good, port=port)
    assert result == CLEAN


def test_f4_port_n_allowed_hosts_follows_port():
    other = container("app", port=8971)
    result = run("app", IMAGE, other, other, port=8970)
    assert result == VALUE_FALSE


TARGETS_BAD = [pytest.param(value, id=name) for name, value in
               (("upper", "APP"), ("other", "holder"), ("none", None), ("str-subclass", StrSub("app")), ("empty", ""))]


@pytest.mark.parametrize("target", TARGETS_BAD)
def test_f4_port_n_target_exact(target):
    good = container("app")
    refusal(lambda: env.compare_window_env(IMAGE, good, good, target=target, port=PORT))


# ---------------------------------------------------------------- F4-BITE-ORDER

def order_fixtures(kind):
    creation = container(kind)
    return (IMAGE, creation, swapped(creation)), (IMAGE, creation, tuple(creation))


def order_blind(observed, creation):
    return sorted(observed) == sorted(creation)


@pytest.mark.parametrize("kind", KINDS)
def test_f4_bite_order_n(kind, monkeypatch):
    negative, _ = order_fixtures(kind)
    assert run(kind, *negative) == ORDER_FALSE
    monkeypatch.setattr(env, "_ordered_equal", order_blind)
    bitten = run(kind, *negative)
    monkeypatch.undo()
    assert bitten == CLEAN  # with the ordered comparison disabled, N is no longer false
    assert run(kind, *negative) == ORDER_FALSE


@pytest.mark.parametrize("kind", KINDS)
def test_f4_bite_order_c(kind, monkeypatch):
    _, clean = order_fixtures(kind)
    before = run(kind, *clean)
    monkeypatch.setattr(env, "_ordered_equal", order_blind)
    bitten = run(kind, *clean)
    assert (before, bitten) == (CLEAN, CLEAN)


# ---------------------------------------------------------------- F4-RAW-EXPORT

class LeakyResult:
    def __repr__(self):
        return f"LeakyResult(env=[{SECRET_KEY}={SECRET_VAL}])"


def test_f4_raw_export_n():
    # The detector itself must fail a result or error that carries a canary.
    planted = (LeakyResult(), ValueError(f"bad token {SECRET_VAL}"), ValueError(SECRET_KEY))
    assert [leaks(item) for item in planted] == [True, True, True]
    chained = env.TargetRefused(EI)
    chained.__context__ = KeyError(SECRET_KEY)
    assert leaks(chained) is True


def export_corpus():
    good = container("app")
    yield run("app", IMAGE, good, good)
    yield run("app", IMAGE, without(good, SECRET_KEY), without(good, SECRET_KEY))
    yield run("app", IMAGE, good + (f"{SECRET_KEY}=other",), good + (f"{SECRET_KEY}=other",))
    yield run("app", IMAGE, good, swapped(good))
    yield case()
    yield case(observed_argv=(SECRET_VAL,))
    bad_tokens = (f"{SECRET_KEY}\x00={SECRET_VAL}", f"={SECRET_VAL}", f"{SECRET_KEY}", f"{SECRET_KEY}={SECRET_VAL}\x00")
    for token in bad_tokens:
        for call in (lambda t=token: run("app", IMAGE + (t,), good, good),
                     lambda t=token: run("forwarder", IMAGE, IMAGE, IMAGE + (t,)),
                     lambda t=token: case(recipe=CASE_ENV + (t,))):
            with pytest.raises(env.TargetRefused) as info:
                call()
            yield info.value
    with pytest.raises(env.TargetRefused) as info:
        run("a5-case", IMAGE + (f"{SECRET_KEY}={SECRET_VAL}",), good, good)
    yield info.value


def test_f4_raw_export_c():
    outputs = list(export_corpus())
    leaked = [type(item).__name__ for item in outputs if leaks(item)]
    reasons = {item.reason for item in outputs if isinstance(item, env.EnvAssessment)}
    codes = {item.code for item in outputs if isinstance(item, env.TargetRefused)}
    assert leaked == [], "Env canary exported"
    assert (reasons, codes) == ({"NONE", "ENV_VALUE", "ENV_DUPLICATE", "ENV_ORDER"}, {EI})


# ---------------------------------------------------------------- A7 codes, API shape, purity

def test_eleven_codes_exact():
    assert env.REFUSAL_CODES == CODES and len(CODES) == 11 and env.EVIDENCE_INVALID == EI
    for code in CODES:
        exc = env.TargetRefused(code)
        assert (exc.args, str(exc), repr(exc), exc.code) == ((code,), code, f"TargetRefused('{code}')", code)
        assert isinstance(exc, ValueError)
        with pytest.raises(AttributeError):
            exc.code = EI
    for bad in ("TARGET_OTHER", "", None, StrSub(EI)):
        with pytest.raises(ValueError) as info:
            env.TargetRefused(bad)
        assert type(info.value) is ValueError


def test_signatures_exact_without_defaults_or_dispatch():
    positional = inspect.Parameter.POSITIONAL_OR_KEYWORD
    keyword = inspect.Parameter.KEYWORD_ONLY
    window = inspect.signature(env.compare_window_env)
    a5 = inspect.signature(env.compare_a5_env)
    assert [(p.name, p.kind, p.annotation) for p in window.parameters.values()] == [
        ("image_env", positional, "tuple"), ("creation_env", positional, "tuple"), ("observed_env", positional, "tuple"),
        ("target", keyword, "str"), ("port", keyword, "int")]
    assert [(p.name, p.kind, p.annotation) for p in a5.parameters.values()] == [
        ("image_env", positional, "tuple"), ("creation_env", positional, "tuple"), ("observed_env", positional, "tuple"),
        ("expected_argv", keyword, "tuple"), ("observed_argv", keyword, "tuple"), ("expected_env", keyword, "tuple")]
    assert (window.return_annotation, a5.return_annotation) == ("EnvAssessment", "EnvAssessment")
    defaults = [p for sig in (window, a5) for p in sig.parameters.values() if p.default is not p.empty]
    assert defaults == []
    public = sorted(name for name, value in vars(env).items()
                    if inspect.isfunction(value) and not name.startswith("_") and value.__module__ == env.__name__)
    assert public == ["compare_a5_env", "compare_window_env"]
    good = container("app")
    with pytest.raises(TypeError):
        env.compare_window_env(IMAGE, good, good, "app", PORT)
    with pytest.raises(TypeError):
        env.compare_window_env(IMAGE, good, good, target="app")
    with pytest.raises(TypeError):
        env.compare_window_env(IMAGE, good, good, target="app", port=PORT, profile="window")
    with pytest.raises(TypeError):
        env.compare_a5_env(IMAGE, good, good, expected_argv=CASE_ARGV, observed_argv=CASE_ARGV)


def test_env_assessment_immutable_and_consistent():
    assert [field.name for field in dataclasses.fields(env.EnvAssessment)] == [
        "trust", "env_matches", "creation_matches", "reason"]
    assert env.REASONS == ("NONE", "ENV_VALUE", "ENV_DUPLICATE", "ENV_ORDER") and env.TRUST == "UNTRUSTED"
    result = case()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.env_matches = False
    assert hasattr(result, "__dict__") is False and hash(result) == hash(CLEAN)
    valid = [(True, True, "NONE"), (False, True, "ENV_VALUE"), (False, False, "ENV_VALUE"),
             (False, True, "ENV_DUPLICATE"), (False, False, "ENV_DUPLICATE"), (False, False, "ENV_ORDER")]
    for values in valid:
        assert env.EnvAssessment("UNTRUSTED", *values).reason == values[2]
    invalid = [("TRUSTED", True, True, "NONE"), (StrSub("UNTRUSTED"), True, True, "NONE"),
               ("UNTRUSTED", 1, True, "NONE"), ("UNTRUSTED", True, 1, "NONE"), ("UNTRUSTED", True, True, "OK"),
               ("UNTRUSTED", True, True, "ENV_VALUE"), ("UNTRUSTED", False, True, "NONE"),
               ("UNTRUSTED", True, False, "NONE"), ("UNTRUSTED", False, True, "ENV_ORDER")]
    for values in invalid:
        refusal(lambda v=values: env.EnvAssessment(*v))


def test_module_is_pure_stdlib_without_normalization_or_recipes():
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert imports == {"__future__", "re", "dataclasses"}
    assert names & {"open", "exec", "eval", "compile", "print", "input", "__import__", "sorted"} == set()
    assert attrs & {"sort", "strip", "lower", "upper", "casefold", "normalize", "setdefault", "environ"} == set()
    assert [literal for literal in ("probe_client", "server.py", "forward.py") if literal in source] == []


# ---------------------------------------------------------------- P4-04, P4-05, P4-11, P4-12 extras

NORMALIZATION = [
    pytest.param("PATH", "path=/usr/local/bin:/usr/bin", id="key-case"),
    pytest.param("LANG", "LANG= C.UTF-8", id="value-leading-space"),
    pytest.param("LANG", "LANG=C.UTF-8 ", id="value-trailing-space"),
    pytest.param("EQ", "EQ=a=b==c\n", id="value-trailing-newline"),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(("key", "token"), NORMALIZATION)
def test_no_normalization_n(kind, key, token):
    bad = replaced(container(kind), key, token)
    result = run(kind, IMAGE, bad, bad)
    assert result == VALUE_FALSE


@pytest.mark.parametrize("kind", KINDS)
def test_no_unicode_normalization_n_and_c(kind):
    composed, decomposed = "CAFE=caf\u00e9", "CAFE=cafe\u0301"
    image = IMAGE + (composed,)
    good, bad = container(kind, image), replaced(container(kind, image), "CAFE", decomposed)
    results = (run(kind, image, good, good), run(kind, image, bad, bad))
    assert results == (CLEAN, VALUE_FALSE)


CONTAINER_MALFORMED = [
    pytest.param(None, id="none"),
    pytest.param([], id="empty-list"),
    pytest.param(TupleSub(), id="tuple-subclass"),
    pytest.param((f"BIG={'x' * (MAX - 3)}",), id="over-byte-bound"),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("position", ("creation", "observed"))
@pytest.mark.parametrize("bad", CONTAINER_MALFORMED)
def test_missing_vs_explicit_null_n_containers(kind, position, bad):
    good = container(kind)
    arrays = (IMAGE, bad, good) if position == "creation" else (IMAGE, good, bad)
    refusal(lambda: run(kind, *arrays))


@pytest.mark.parametrize("kind", KINDS)
def test_missing_vs_explicit_null_c_explicit_empty_is_data(kind):
    # () is explicit data judged on its merits; None is never defaulted to [] (P4-05).
    result = run(kind, (), (), ())
    expected = CLEAN if kind in ("forwarder", "a5-holder") else VALUE_FALSE
    assert result == expected


CALIBRATION_RUNTIME = {
    "image": "sha256:" + "a" * 64,
    "command": ["python3", "/app/server.py"],
    "internal_port": 8000,
    "workdir": "/app",
    "env": {"HOST": "0.0.0.0", "PORT": "8000", "DATA_DIR": "/data", "ALLOWED_HOSTS": f"100.110.162.4:{PORT},scanapp:8080"},
}
CALIBRATION_RUNTIME_SHA256 = "fee1d0d84c7c4f7619be187e8b80cfbaa22b744b7822270ef130b3710ec66f85"


def runtime_sha256(runtime):
    return hashlib.sha256(json.dumps(runtime, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def test_four_key_calibration_runtime_hash_unchanged():
    before = runtime_sha256(CALIBRATION_RUNTIME)
    good = container("app")
    result = run("app", IMAGE, good, good)
    after = runtime_sha256(CALIBRATION_RUNTIME)
    # Inherited baseline keys widen the compared container map, never the four-key runtime.
    assert (before, after, result) == (CALIBRATION_RUNTIME_SHA256, CALIBRATION_RUNTIME_SHA256, CLEAN)
    assert env._app_overrides(PORT) == CALIBRATION_RUNTIME["env"]
    assert tuple(CALIBRATION_RUNTIME["env"]) == env.APP_KEYS
