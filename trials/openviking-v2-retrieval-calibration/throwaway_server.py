"""External-only real OpenViking 0.5.4 lifecycle. Never reads the live configuration."""
from __future__ import annotations

import contextlib
import functools
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from calibration_core import append, install_guard, now, save, validate_endpoint

MODEL = 'BAAI/bge-small-en-v1.5'
PYTHON = '/home/shinelay/.openviking/venv/bin/python'


def child_main(conf, port, audit):
    install_guard(port, Path(audit))
    sys.path.insert(0, '/home/shinelay/.openviking')
    import run_server
    run_server._patch_local_embedder()
    run_server.TextEmbedding = functools.partial(run_server.TextEmbedding, threads=2, local_files_only=True)
    sys.argv = ['calibration-server', '--config', conf, '--host', '127.0.0.1', '--port', str(port)]
    from openviking.server.bootstrap import main
    main()


class Throwaway:
    def __init__(self, state):
        if importlib.metadata.version('openviking') != '0.5.4':
            raise ValueError('E_OPENVIKING_VERSION: require 0.5.4')
        self.root = Path(tempfile.mkdtemp(prefix='ov-data21-'))
        self.state = state
        self.child = None
        self.log = None
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        validate_endpoint('127.0.0.1', self.port, self.port)
        self.base = f'http://127.0.0.1:{self.port}'

    def request(self, route, payload=None, owner='default'):
        validate_endpoint('127.0.0.1', self.port, self.port)
        headers = {'Content-Type': 'application/json', 'X-OpenViking-Account': 'default',
                   'X-OpenViking-User': owner, 'X-OpenViking-Agent': owner}
        req = urllib.request.Request(self.base + route, headers=headers,
                                     data=None if payload is None else json.dumps(payload).encode())
        with urllib.request.urlopen(req, timeout=240) as response:
            result = json.load(response)
        append(self.state / 'http.jsonl', {'at': now(), 'port': self.port, 'route': route,
                                          'method': 'GET' if payload is None else 'POST', 'owner': owner})
        if result.get('status') == 'error':
            raise RuntimeError(f'E_THROWAWAY_API: {route}: {result.get("error")}')
        return result

    def __enter__(self):
        self.root.chmod(0o700)
        config = {
            'storage': {'workspace': str(self.root / 'data'), 'vectordb': {'backend': 'local'}, 'agfs': {'backend': 'local'}},
            'embedding': {'dense': {'provider': 'local', 'model': MODEL, 'dimension': 384}},
            'vlm': {'provider': 'openai', 'model': 'never-called', 'api_key': 'throwaway-placeholder', 'api_base': 'http://127.0.0.1:9/v1'},
            'server': {'agent_evolution': {'enabled': False}},
            'memory': {'extraction_enabled': False, 'session_skill_extraction_enabled': False},
        }
        config_path = self.root / 'ov.conf'
        save(config_path, config)
        config_path.chmod(0o600)
        env = {**os.environ, 'HOME': str(self.root), 'OPENVIKING_CONFIG_FILE': str(config_path),
               'HF_HUB_OFFLINE': '1', 'FASTEMBED_CACHE_PATH': '/tmp/fastembed_cache'}
        self.log = (self.root / 'server.log').open('w')
        self.child = subprocess.Popen([PYTHON, str(Path(__file__).resolve()), '--child', str(config_path), str(self.port), str(self.state / 'child-audit.jsonl')],
                                      cwd=self.root, env=env, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)
        append(self.state / 'server-attempts.jsonl', {'at': now(), 'tmp_root': str(self.root), 'port': self.port, 'pid': self.child.pid,
                                                   'openviking': '0.5.4', 'workspace': config['storage']['workspace']})
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if self.child.poll() is not None:
                    raise RuntimeError(f'E_THROWAWAY_START: exit {self.child.returncode}; log {self.root}/server.log')
                try:
                    self.request('/health')
                    return self
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.25)
            raise RuntimeError(f'E_THROWAWAY_HEALTH: {self.root}/server.log')
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.child is not None:
            self.child.terminate()
            try:
                self.child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
        if self.log:
            self.log.close()
        # Retain only temp evidence for diagnostics, never copy model payloads into artifacts.

    def seed(self, items):
        for index, item in enumerate(items):
            text = f"# {item['headline']}\n{item['body']}\n"
            self.request('/api/v1/content/write', {'uri': item['uri'], 'content': text, 'mode': 'replace',
                                                  'wait': True, 'processing_mode': 'vectors_only'}, item['owner'] if item['owner'] != 'resource' else 'default')
            if index % 50 == 0:
                print(f'seed {index+1}/{len(items)}', flush=True)

    def find(self, query, target, limit=8, owner='default'):
        response = self.request('/api/v1/search/find', {'query': query, 'target_uri': target, 'node_limit': limit, 'score_threshold': 0.0}, owner)
        found = response.get('result', {})
        hits = []
        for key in ['resources', 'memories', 'skills']:
            for hit in found.get(key, []):
                hits.append({'uri': hit['uri'], 'score': float(hit.get('score', 0)), 'level': hit.get('level')})
        return sorted(hits, key=lambda h: (-h['score'], h['uri']))


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != '--child':
        raise SystemExit('Only the calibration runner may start this child')
    with contextlib.suppress(KeyboardInterrupt):
        child_main(sys.argv[2], int(sys.argv[3]), sys.argv[4])
