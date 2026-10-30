"""Known-answer static capability controls; no application dependencies or imports."""

import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import asdict
from pathlib import Path
from textwrap import dedent

import pytest

BIN = Path(__file__).resolve().parents[2] / "configs" / "epd" / "bin"


@pytest.fixture
def capabilities(monkeypatch):
    monkeypatch.syspath_prepend(str(BIN))
    spec = importlib.util.spec_from_file_location("capabilities_under_test", BIN / "capabilities.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def write_sources(root, sources):
    for relative, source in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(source).lstrip('\n'))


def git(root, *args):
    return subprocess.run(
        ['git', '-C', str(root), *args], check=True, capture_output=True,
    ).stdout


def keys(caps):
    return {cap.key for cap in caps}


def test_same_file_methods_and_hints(capabilities, tmp_path):
    source = '''\
        router = APIRouter(prefix="/v1", tags=["fruit", "unused"])
        @router.get("/items", summary="Read items")
        @router.post("/items")
        @router.put("/items")
        @router.patch("/items")
        @router.delete("/items")
        @router.head("/items")
        @router.options("/items")
        async def items():
            """Item operations.\n\nMore detail."""
        app = FastAPI()
        @app.get("")
        def home(): pass
    '''
    # Keep the docstring's multiline content indented with its surrounding source.
    write_sources(tmp_path, {'app.py': source.replace('More detail.', '            More detail.')})
    caps = capabilities.probe_fastapi(tmp_path)
    assert keys(caps) == {f'{verb} /v1/items' for verb in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']} | {'GET /'}
    for cap in caps:
        if cap.key == 'GET /':
            assert (cap.where, cap.group) == ('app.py:15', 'app.py')
        else:
            assert (cap.where, cap.group) == ('app.py:9', 'fruit')
            assert cap.intent == ('Read items' if cap.key == 'GET /v1/items' else 'Item operations.')


@pytest.mark.parametrize('layout', ['backend', 'src', 'src/backend'])
@pytest.mark.parametrize(('binding', 'receiver', 'exports'), [
    ('from fruit.api.base import router', 'router', {}),
    ('from fruit.api.base import router as api', 'api', {}),
    ('from .base import router', 'router', {}),
    ('from ..api.base import router', 'router', {}),
    ('import fruit.api.base as definitions', 'definitions.router', {}),
    ('import fruit.api.base', 'fruit.api.base.router', {}),
    ('from fruit.api import base as definitions', 'definitions.router', {}),
    ('from fruit.exports import api', 'api', {'exports.py': 'from .api.base import router as api'}),
    ('from fruit import router', 'router', {'__init__.py': 'from .api.base import router'}),
    ('from fruit.api.base import router\nsaved = router\nrouter = object()', 'saved', {}),
])
def test_imports_aliases_and_reexports(capabilities, tmp_path, layout, binding, receiver, exports):
    files = {
        '__init__.py': '',
        'api/__init__.py': '',
        'api/base.py': 'from fastapi import APIRouter as Router\nrouter: object = Router(prefix="/v2", tags=["fruit"])',
        **exports,
        'api/routes.py': f'{binding}\n@{receiver}.post("/items", summary="Create item")\nasync def create(): pass',
    }
    write_sources(tmp_path, {f'{layout}/fruit/{name}': value for name, value in files.items()})
    caps = capabilities.probe_fastapi(tmp_path)
    assert [asdict(cap) for cap in caps] == [{
        'kind': 'http', 'key': 'POST /v2/items', 'group': 'fruit', 'intent': 'Create item',
        'where': f'{layout}/fruit/api/routes.py:{len(binding.splitlines()) + 2}',
    }]


@pytest.mark.parametrize('layout', ['src', 'backend', 'custom'])
def test_package_roots_and_namespace_layouts(capabilities, tmp_path, layout):
    files = {
        f'{layout}/fruit/base.py': 'import fastapi as fa\nrouter = fa.APIRouter(prefix="/fruit")',
        f'{layout}/fruit/routes.py': 'from fruit.base import router\n@router.get("/items")\ndef items(): pass',
    }
    # A nonstandard source root needs an explicit package; src/backend also
    # support namespace packages. No sys.path or installed-module search.
    if layout == 'custom':
        files[f'{layout}/fruit/__init__.py'] = ''
    write_sources(tmp_path, files)
    assert keys(capabilities.probe_fastapi(tmp_path)) == {'GET /fruit/items'}


@pytest.mark.parametrize('binding', [
    'from unavailable import router',
    'import unavailable as foreign\nrouter = foreign.router',
    'router = object()',
    'router = APIRouter()\nrouter = object()',
    'router = APIRouter()\ndel router',
    'router = APIRouter()\nrouter += other',
    'router = APIRouter()\nif unknown:\n    router = object()',
    'router = APIRouter()\ndef router(): pass',
    'router = APIRouter()\nclass router: pass',
    'router = APIRouter()\nfrom unavailable import *',
    'from unrelated import APIRouter\nrouter = APIRouter()',
    'class APIRouter: pass\nrouter = APIRouter()',
    'import unrelated\nrouter = unrelated.APIRouter()',
    'from fastapi import APIRouter\nAPIRouter = object\nrouter = APIRouter()',
    'def factory():\n    return APIRouter()\nrouter = factory()',
    'import importlib\nrouter = importlib.import_module("fruit.base").router',
    'from fruit import base\nbase.router = object()\nrouter = base.router',
    'from fruit import base\ndel base.router\nrouter = base.router',
])
def test_unknown_and_shadowed_bindings_are_not_routes(capabilities, tmp_path, binding):
    write_sources(tmp_path, {
        'app.py': f'{binding}\n@router.get("/not-real")\ndef ignored(): pass',
        'unrelated.py': 'def APIRouter(): return object()',
        'fruit/__init__.py': '',
        'fruit/base.py': 'router = APIRouter(prefix="/fruit")',
    })
    assert capabilities.probe_fastapi(tmp_path) == []


def test_bindings_respect_statement_order_and_scope(capabilities, tmp_path):
    write_sources(tmp_path, {'app.py': '''
        @router.get("/too-early")
        def too_early(): pass
        router = APIRouter()
        @router.get("/real")
        def real(): pass
        saved = router
        router = object()
        @router.get("/shadowed")
        def shadowed(): pass
        @saved.get("/saved")
        def saved_route(): pass
        def factory():
            saved = object()
            @saved.get("/nested")
            def nested(): pass
        class View:
            @saved.get("/class")
            def member(): pass
        if unknown:
            @saved.get("/conditional")
            def conditional(): pass
    '''})
    assert keys(capabilities.probe_fastapi(tmp_path)) == {'GET /real', 'GET /saved'}


def test_nonliteral_prefix_is_unknown_and_include_prefix_not_guessed(capabilities, tmp_path):
    write_sources(tmp_path, {'app.py': '''
        from fastapi import FastAPI, APIRouter
        app = FastAPI()
        router = APIRouter(prefix=runtime_prefix(), tags=["fruit"])
        app.include_router(router, prefix="/mount")
        @router.get("/items")
        def items(): pass
        @router.get(dynamic_path)
        def dynamic(): pass
    '''})
    caps = capabilities.probe_fastapi(tmp_path)
    assert keys(caps) == {'GET ?/items'}
    assert caps[0].group == 'fruit'


@pytest.mark.parametrize('extra', [
    {'src/fruit/base.py': 'router = APIRouter(prefix="/second")', 'src/fruit/__init__.py': ''},
    {'backend/fruit/base/__init__.py': 'router = APIRouter(prefix="/second")'},
    {'src/fruit/other.py': '', 'src/fruit/__init__.py': ''},
])
def test_ambiguous_modules_or_parents_are_not_guessed(capabilities, tmp_path, extra):
    write_sources(tmp_path, {
        'backend/fruit/__init__.py': '',
        'backend/fruit/base.py': 'router = APIRouter(prefix="/first")',
        'app.py': 'from fruit.base import router\n@router.get("/items")\ndef items(): pass',
        **extra,
    })
    assert capabilities.probe_fastapi(tmp_path) == []


def test_cyclic_unresolved_and_invalid_sources_do_not_hide_good_routes(capabilities, tmp_path):
    write_sources(tmp_path, {
        'fruit/__init__.py': 'from .cycle import router',
        'fruit/cycle.py': 'from . import router',
        'fruit/broken.py': 'this is invalid python !!!',
        'fruit/escape.py': 'from ..outside import router',
        'outside.py': 'router = APIRouter(prefix="/outside")',
        'cycle.py': 'from fruit import router\n@router.get("/cycle")\ndef cycle(): pass',
        'broken.py': 'from fruit.broken import router\n@router.get("/broken")\ndef broken(): pass',
        'escape.py': 'from fruit.escape import router\n@router.get("/escape")\ndef escape(): pass',
        'good.py': 'router = APIRouter()\n@router.get("/good")\ndef good(): pass',
    })
    assert keys(capabilities.probe_fastapi(tmp_path)) == {'GET /good'}


@pytest.mark.parametrize('checkout', [False, True])
def test_admitted_sources_are_the_only_import_boundary(capabilities, tmp_path, checkout):
    root = tmp_path / 'repository'
    excluded = ['tests', 'fixtures', 'examples', 'vendor', 'vendored', 'node_modules', '.venv', 'nested']
    files = {'good.py': 'router = APIRouter()\n@router.get("/good")\ndef good(): pass'}
    for folder in excluded:
        files[f'{folder}/base.py'] = 'router = APIRouter(prefix="/excluded")\n@router.get("/direct")\ndef direct(): pass'
        files[f'consumer_{folder.replace(".", "")}.py'] = f'from {folder}.base import router\n@router.get("/{folder}")\ndef imported(): pass'
    files['test_base.py'] = 'router = APIRouter()'
    files['conftest.py'] = 'router = APIRouter()'
    files['test_consumer.py'] = 'router = APIRouter()\n@router.get("/test")\ndef test_route(): pass'
    files['consumer.py'] = 'from test_base import router\n@router.get("/test-import")\ndef imported(): pass'
    files['consumer_config.py'] = 'from conftest import router\n@router.get("/config-import")\ndef imported(): pass'
    files['consumer_link.py'] = 'from linked import router\n@router.get("/linked")\ndef imported(): pass'
    files['consumer_package.py'] = 'from linked_package.base import router\n@router.get("/linked-package")\ndef imported(): pass'
    write_sources(root, files)
    outside = tmp_path / 'outside'
    write_sources(outside, {'base.py': 'router = APIRouter()\n@router.get("/outside")\ndef outside(): pass'})
    (root / 'linked.py').symlink_to(outside / 'base.py')
    (root / 'linked_package').symlink_to(outside, target_is_directory=True)
    # Even tracked files underneath a later nested repository stay excluded.
    if checkout:
        git(root, 'init', '-q')
        git(root, 'add', '.')
    (root / 'nested/.git').mkdir()
    if checkout:
        write_sources(root, {
            'untracked.py': 'router = APIRouter()\n@router.get("/untracked")\ndef untracked(): pass',
            'untracked_consumer.py': 'from untracked import router\n@router.get("/untracked-import")\ndef imported(): pass',
        })
        git(root, 'add', 'untracked_consumer.py')
        (root / 'inside_link.py').symlink_to(root / 'untracked.py')
        git(root, 'add', 'inside_link.py')
    assert keys(capabilities.probe_fastapi(root)) == {'GET /good'}


def test_checkout_and_plain_export_agree_without_executing_target(capabilities, tmp_path):
    root = tmp_path / 'checkout'
    sentinel = tmp_path / 'target-was-imported'
    write_sources(root, {
        'backend/fruit/__init__.py': f'from pathlib import Path\nPath({str(sentinel)!r}).touch()\nraise RuntimeError("target executed")',
        'backend/fruit/base.py': 'router = APIRouter(prefix="/fruit", tags=["fruit"])',
        'backend/fruit/routes.py': 'from .base import router as api\n@api.get("/items")\ndef items(): pass',
        'backend/fruit/routes_alias.py': 'import fruit.base as base\n@base.router.post("/items")\ndef create(): pass',
    })
    git(root, 'init', '-q')
    git(root, 'add', '.')
    tree = git(root, 'write-tree').decode().strip()
    archive = git(root, 'archive', '--format=tar', tree)
    exported = tmp_path / 'export'
    exported.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(exported, filter='data')
    checkout_caps = capabilities.probe_fastapi(root)
    export_caps = capabilities.probe_fastapi(exported)
    assert keys(checkout_caps) == {'GET /fruit/items', 'POST /fruit/items'}
    assert sorted((asdict(cap) for cap in checkout_caps), key=lambda cap: cap['key']) == sorted((asdict(cap) for cap in export_caps), key=lambda cap: cap['key'])
    assert not sentinel.exists()


def test_direct_local_call_preserves_nested_application_route(capabilities, tmp_path):
    write_sources(tmp_path, {'app.py': '''
        from fastapi import FastAPI
        def attach(app: FastAPI, directory):
            @app.get("/shell")
            async def shell(): pass
        def create_app():
            app = FastAPI()
            app.state.ready = True
            app.state.mounted = attach(app, directory=unknown_path)
            return app
        app = create_app
    '''})
    caps = capabilities.probe_fastapi(tmp_path)
    assert [asdict(cap) for cap in caps] == [{
        'kind': 'http', 'key': 'GET /shell', 'where': 'app.py:4',
        'group': 'app.py', 'intent': '',
    }]


@pytest.mark.parametrize('calls', [
    'attach(first)\nattach(second)',
    'attach(app=first)\nattach(second)',
    'def build():\n    local = APIRouter(prefix="/v3", tags=["fruit"])\n    attach(local)',
])
def test_consistent_router_arguments_keep_prefix_tag_and_location(capabilities, tmp_path, calls):
    write_sources(tmp_path, {'app.py': f'''\
def attach(app):
    @app.post("/items")
    def items(): pass
first = APIRouter(prefix="/v3", tags=["fruit"])
second = APIRouter(prefix="/v3", tags=["fruit"])
{calls}
'''})
    caps = capabilities.probe_fastapi(tmp_path)
    assert [asdict(cap) for cap in caps] == [{
        'kind': 'http', 'key': 'POST /v3/items', 'where': 'app.py:3',
        'group': 'fruit', 'intent': '',
    }]


@pytest.mark.parametrize('calls', [
    '',  # A type annotation alone proves nothing, even with a same-name app elsewhere.
    'attach(unknown)',
    'attach(good)\nattach(unknown)',
    'attach(good)\nattach(APIRouter(prefix="/different"))',
    'attach(good)\nattach(APIRouter(prefix="/known", tags=["other"]))',
    'attach = object()\nattach(good)',
    'def caller():\n    attach = unknown\n    attach(good)',
    'def caller(attach):\n    attach(good)',
    'good = unknown\nattach(good)',
    'attach(*[good])',
    'attach(**{"app": good})',
    'attach(good, app=good)',
    'attach(good, extra=good)',
    'attach(good, good)',
    'attach()',
    'alias = attach\nalias(good)',  # Callable aliases are not direct named calls.
    'attach(factory())',
])
def test_unknown_conflicting_or_shadowed_calls_supply_no_router(capabilities, tmp_path, calls):
    write_sources(tmp_path, {'app.py': f'''\
def attach(app: FastAPI):
    @app.get("/not-proven")
    def handler(): pass
def factory(): return APIRouter(prefix="/known")
good = APIRouter(prefix="/known")
app = FastAPI()
{calls}
'''})
    assert capabilities.probe_fastapi(tmp_path) == []


@pytest.mark.parametrize('extra', ['', 'attach(FastAPI())'])
def test_recursive_parameter_resolution_terminates_conservatively(capabilities, tmp_path, extra):
    write_sources(tmp_path, {'app.py': f'''\
def attach(app):
    @app.get("/cycle")
    def handler(): pass
    forward(app)
def forward(app):
    attach(app)
{extra}
'''})
    assert capabilities.probe_fastapi(tmp_path) == []


def test_lexical_bindings_never_match_a_sibling_scope(capabilities, tmp_path):
    write_sources(tmp_path, {'app.py': '''
        def unused():
            router = APIRouter(prefix="/wrong-scope")
        def attach(router):
            @router.get("/unproven")
            def handler(): pass
        def local():
            router = APIRouter(prefix="/local")
            @router.get("/real")
            def handler(): pass
        def shadowed():
            @router.get("/unbound")
            def handler(): pass
            router = APIRouter(prefix="/late")
        def mutate(app):
            app = object()
            @app.get("/shadowed")
            def handler(): pass
        mutate(FastAPI())
    '''})
    assert keys(capabilities.probe_fastapi(tmp_path)) == {'GET /local/real'}


def test_parameter_forwarding_across_direct_calls(capabilities, tmp_path):
    write_sources(tmp_path, {'app.py': '''
        def mount(*, app):
            @app.get("/shell")
            def handler(): pass
        def attach(app, /):
            mount(app=app)
        def create():
            app = FastAPI()
            attach(app)
    '''})
    assert keys(capabilities.probe_fastapi(tmp_path)) == {'GET /shell'}


def test_derive_preserves_other_probes_and_authored_map(capabilities, tmp_path):
    write_sources(tmp_path, {
        'api.py': 'router = APIRouter()\n@router.get("/items")\ndef items():\n    """Derived seed, not the authored intent."""',
        'web.tsx': '<Route path="/fruit" element={<Layout/>}><Route index element={<Fruit/>}/><Route path="new" element={<New/>}/></Route>',
        'cli.py': 'parser = commands.add_parser("list", help="List items")',
    })
    surface = capabilities.derive(tmp_path)
    expected = {'GET /items', '/fruit', '/fruit/new', 'list'}
    assert keys(surface.caps) == expected
    assert surface.probes_matched == ['fastapi', 'react-router', 'argparse-cli']
    assert next(cap.intent for cap in surface.caps if cap.key == 'list') == 'List items'
    intents = {key: f'Written intent for `{key}` — keep café intact.' for key in expected}
    preamble = 'For people who track fruit.\n\nSecond paragraph, with `markup` and café.'
    path = tmp_path / 'map.md'
    first = capabilities.render(tmp_path, surface, intents, preamble)
    path.write_text(first)
    assert capabilities.check(surface, path) == ([], [], [])
    parsed_intents, parsed_preamble = capabilities.parse_map(path)
    assert parsed_intents == intents
    assert parsed_preamble == preamble
    assert capabilities.render(tmp_path, surface, parsed_intents, parsed_preamble) == first
    raw_preamble = re.search(r'## What this is\n(.*?)(?=\n## )', first, re.S).group(1)
    assert raw_preamble.encode() == ('\n' + preamble + '\n').encode()


def test_exported_cli_refresh_is_idempotent_with_stdlib_only(capabilities, tmp_path):
    root = tmp_path / 'project'
    exported_bin = tmp_path / 'bin'
    exported_bin.mkdir()
    for name in ['capabilities.py', 'fastapi_router_bindings.py']:
        shutil.copyfile(BIN / name, exported_bin / name)
    write_sources(root, {
        'fruit/__init__.py': '',
        'fruit/base.py': 'from fastapi import APIRouter\nrouter = APIRouter(prefix="/fruit")',
        'fruit/routes.py': 'from .base import router\n@router.get("/items")\ndef items(): pass',
    })
    command = [sys.executable, '-E', '-S', str(exported_bin / 'capabilities.py'), '--repo', str(root)]
    derived = subprocess.run([*command, '--json'], check=True, capture_output=True, text=True)
    assert {cap['key'] for cap in json.loads(derived.stdout)['capabilities']} == {'GET /fruit/items'}
    path = root / '.temper/topics/capabilities.md'
    path.parent.mkdir(parents=True)
    text = capabilities.render(root, capabilities.derive(root), {'GET /fruit/items': 'Authored sentence.'}, 'Authored preamble.')
    path.write_text(text)
    for _ in range(2):
        subprocess.run(command, check=True, capture_output=True, text=True)
        assert path.read_bytes() == text.encode()
    checked = subprocess.run([*command, '--check', '--strict'], check=True, capture_output=True, text=True)
    assert checked.stdout == 'ok: 1 capabilities, map agrees\n'
