"""Pure metrics, immutable unit plan, durable journal, and experiment isolation."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from datetime import UTC, datetime

FORBIDDEN = ('/home/shinelay/.openviking/data', '/home/shinelay/.pi/openviking')


def now():
    return datetime.now(UTC).isoformat()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def append(path, value):
    with path.open('a') as f:
        f.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def recall(expected, returned, k=5):
    target = set(expected)
    if not target:
        raise ValueError('Recall requires a nonempty expected set')
    return len(target.intersection(dict.fromkeys(returned[:k]))) / len(target)


def noise(returned_by_negative):
    if not returned_by_negative:
        raise ValueError('Noise requires negative queries')
    return sum(bool(x) for x in returned_by_negative) / len(returned_by_negative)


def wilson(successes, n):
    if not n:
        return None
    z = 1.959963984540054
    p = successes / n
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return [max(0, c-h), min(1, c+h)]


def cosine(a, b):
    den = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    if not den:
        raise ValueError('Zero vector')
    return sum(x*y for x, y in zip(a, b, strict=True)) / den


def paired_delta(before, after):
    return after - before


def validate_endpoint(host, port, allowed_port):
    if host not in ('127.0.0.1', 'localhost', '::1') or port == 1933 or port != allowed_port:
        raise PermissionError(f'E_ISOLATION_NETWORK: {host}:{port}')


def validate_path(value):
    if isinstance(value, (str, bytes, os.PathLike)):
        raw = os.fsdecode(value)
        # Lexical normalization; inputs and temp roots are controlled by the harness.
        normalized = os.path.abspath(os.path.expanduser(raw))
        for root in FORBIDDEN:
            if normalized == root or normalized.startswith(root + '/'):
                raise PermissionError('E_ISOLATION_PATH: forbidden live state')


def install_guard(port, audit_path):
    def guard(event, args):
        try:
            if event == 'open':
                validate_path(args[0])
            elif event in ('os.listdir', 'os.scandir', 'os.remove', 'os.mkdir', 'os.rmdir', 'os.chdir'):
                validate_path(args[0])
            elif event in ('os.rename', 'os.link', 'os.symlink'):
                validate_path(args[0])
                validate_path(args[1])
            elif event == 'socket.connect':
                address = args[1]
                if isinstance(address, tuple):
                    validate_endpoint(address[0], address[1], port)
                    append(audit_path, {'event': 'connect', 'port': address[1], 'at': now()})
                else:
                    raise PermissionError('E_ISOLATION_NETWORK: Unix sockets forbidden')
            elif event == 'socket.getaddrinfo':
                validate_endpoint(args[0], args[1], port)
        except PermissionError as exc:
            append(audit_path, {'event': 'denied', 'reason': str(exc), 'at': now()})
            raise
    sys.addaudithook(guard)


class Journal:
    """Append-only result commits; cursor can be recovered after a crash before cursor save."""

    def __init__(self, folder, plan):
        self.folder = folder
        folder.mkdir(exist_ok=True, parents=True)
        self.plan_path = folder / 'plan.json'
        self.results_path = folder / 'units.jsonl'
        self.attempts_path = folder / 'attempts.jsonl'
        if self.plan_path.exists():
            frozen = json.loads(self.plan_path.read_text())
            if frozen != plan:
                append(self.attempts_path, {'at': now(), 'status': 'conflict', 'error': 'E_PLAN_HASH_CONFLICT', 'offered_hash': digest(plan)})
                raise ValueError('E_PLAN_HASH_CONFLICT')
        else:
            save(self.plan_path, plan)
        self.plan = plan
        self.units = plan['units']
        self.done = {}
        if self.results_path.exists():
            for line in self.results_path.read_text().splitlines():
                row = json.loads(line)
                if row['id'] in self.done:
                    raise ValueError('E_DUPLICATE_UNIT')
                self.done[row['id']] = row
        planned = {u['id']: u for u in self.units}
        for key, row in self.done.items():
            if key not in planned or planned[key]['hash'] != row['hash'] or digest(row['result']) != row['result_hash']:
                raise ValueError('E_UNIT_HASH_CONFLICT')
        if list(self.done) != [u['id'] for u in self.units[:len(self.done)]]:
            raise ValueError('E_CURSOR_ORDER')
        self.cursor = len(self.done)
        cursor_path = folder / 'cursor.json'
        state = {'cursor': self.cursor, 'total': len(self.units)}
        if not cursor_path.exists() or json.loads(cursor_path.read_text()) != state:
            save(cursor_path, state)

    def run(self, execute, max_units=None):
        start = self.cursor
        try:
            for unit in self.units[self.cursor:]:
                if max_units is not None and self.cursor - start >= max_units:
                    break
                result = execute(unit)
                row = {'id': unit['id'], 'hash': unit['hash'], 'result': result, 'result_hash': digest(result)}
                append(self.results_path, row)
                self.done[unit['id']] = row
                self.cursor += 1
                save(self.folder / 'cursor.json', {'cursor': self.cursor, 'total': len(self.units)})
            status = 'complete' if self.cursor == len(self.units) else 'partial'
            append(self.attempts_path, {'at': now(), 'start': start, 'cursor': self.cursor, 'status': status})
            return status
        except BaseException as exc:
            append(self.attempts_path, {'at': now(), 'start': start, 'cursor': self.cursor, 'status': 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'error', 'error': type(exc).__name__ + ': ' + str(exc)})
            raise
