# Exact bounded file observations: ops_host_binding_files (P1)

Module `configs/architecture/bin/ops_host_binding_files.py`, tests
`tests/test_architecture/test_ops_host_binding_files.py`. This is P1 of the P3 host-client ABI: the
r4 ABI paper's A2 and A7 (Architecture #190/#226; paper SHA256SUMS
b06928a274e67f9553a5cec5cf03555c434126e42f6550b49243df291607845b), with Security C1–C5 (Security #63
report 6e6bf82f…, r4 receiving cca348e0109701b2c8516c6e5b1cdc334081a9fed3bd37e267814d28a6a797f4).
Standard library only, and independent: it imports no other temper module, and no other module's
reader is reused.

The module only observes files. It issues no write, create, rename, chmod or unlink call, runs
nothing and opens no network connection. A `FileRead` is caller-held evidence data. It is not a
filesystem capability, an access grant, an issuer or a verified target, and nothing here (or
elsewhere) turns it into one.

## API

```python
read_private_file(root: str, ref: dict, *, uid: int, cap: int) -> FileRead
read_release_file(root: str, ref: dict, *, uid: int, mode: int, cap: int) -> FileRead
recheck_files(reads: tuple[FileRead, ...]) -> None
```

Arguments are exact built-in types, checked before any filesystem call: no `bool`, no subclass, no
coercion, no default uid and no implicit root.

- `root`: an absolute, normalized path (`/` followed by non-empty components, none `.` or `..`, no
  repeated or trailing `/`, no NUL, no backslash, valid UTF-8). It is used as given: never
  resolved, normalized or made absolute.
- `ref`: a closed dict with exactly `path`, `sha256` and `byte_length`. `path` is relative POSIX,
  at most 1024 bytes, components `[A-Za-z0-9._-]{1,128}`, none `.` or `..`. `sha256` is 64
  lowercase hex digits. `byte_length` is an int from 1 to `cap` (private route) or from 0 to `cap`
  (release route: an explicit zero-length source observation is allowed there, never for a
  private publication file).
- `uid`: int ≥ 0, the exact owner required from the root down. The reader never switches uid.
- `mode` (release route only): int 0..0o7777, the exact leaf mode. A private leaf must be exactly
  0o600.
- `cap`: int 1..16777216, the largest size accepted. `byte_length <= cap` is checked before any
  filesystem call.

`FileRead` is immutable, with exactly the fields `root`, `ref`, `raw`, `uid`, `mode`, `cap` and
`stamps`. It keeps no descriptor. `ref` returns a fresh dict on every access, so nobody holds an
alias to the stored one. `repr` and `str` are fixed: `FileRead(path='…', sha256='…',
byte_length=N)`, and never show `raw`.

`Stamp` is one node's full fstat observation: `path`, `dev`, `ino`, `uid`, `mode`, `size`,
`mtime_ns`, `ctime_ns`, `nlink`. The stamps walk: for a `ref.path` of k components, `stamps`
holds exactly k+1 entries in walk order: `.` (the supplied root), then each `/`-joined prefix of
`ref.path`, ending with `ref.path` itself (the leaf). System ancestors above the root are walked
and checked but not stamped.

`recheck_files` validates the whole batch before its first filesystem call. `reads` must be
exactly a `tuple` of 1 to 65536 entries, each exactly a `FileRead`, with every stored field valid
as above (raw exactly `bytes` of length `byte_length`; stamps an exact non-empty tuple of exact
`Stamp` entries, int fields ≥ 0, paths exactly the stamps walk). It then walks and reads every
entry again, and returns `None` only if every stamp, the bytes, the hash and the length are
unchanged.

### Refusals

Every refusal is `TargetRefused` (a `ValueError`) with a read-only `code`. Its args, `str` and
`repr` hold exactly the code: no path, value or OS error detail, and no chained exception.
`CODES` is ABI A7's closed vocabulary of eleven codes; this module raises four of them.

| What happened | `read_private_file` | `read_release_file` | `recheck_files` |
| --- | --- | --- | --- |
| Invalid argument | `TARGET_PUBLICATION_INVALID` | `TARGET_SOURCE_MISSING` | — |
| Invalid batch (container, any entry, any field) | — | — | `TARGET_EVIDENCE_INVALID`, with zero filesystem calls and no entry rechecked |
| Missing or unreadable node, wrong type, owner, mode or nlink, size over cap or not the declared length, short read, no EOF, wrong hash | `TARGET_PUBLICATION_INVALID` | `TARGET_SOURCE_MISSING` | `TARGET_SOURCE_DRIFT` |
| A change seen during the read (pre/post stamps differ, or the leaf's name no longer names the inode read) | `TARGET_SOURCE_DRIFT` | `TARGET_SOURCE_DRIFT` | `TARGET_SOURCE_DRIFT` |
| Anything different from the held read | — | — | `TARGET_SOURCE_DRIFT` |

## The walk

The reader walks every path component from `/`: each ancestor above the root, the root, each
directory of `ref.path`, then the leaf. At each component it:

1. checks the type without following: `fstatat(parent_fd, name, AT_SYMLINK_NOFOLLOW)` must show a
   directory (for every walked directory) or a regular file (for the leaf);
2. opens the name relative to its parent's descriptor with exactly
   `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`, plus `O_DIRECTORY` for a directory;
3. fstats the new descriptor: its dev, ino and file type must equal the precheck's.

### The five guarantees (A2.2), and only these

1. A component whose observed type is not the required one (symlink, FIFO, device, socket, or a
   non-directory where a directory is required) is rejected before it is opened.
2. Every open uses exactly the flags above.
3. An opened descriptor whose dev, ino or type differs from the precheck is refused.
4. A FIFO raced in after a regular precheck is opened without waiting for a writer (`O_NONBLOCK` is
   mandatory) and is then refused by (3).
5. Every descriptor is closed on every outcome.

### The precheck and the open are not atomic

The type check and the open are two separate steps. The name can change between them, and the
identity check runs only after the open. A non-regular node raced in after the precheck is
therefore refused after it has been opened, and no claim is made about any side effect of that
open (for example a device's open-time behaviour). There is no absolute no-side-effect or
no-blocking guarantee; that would need its own named primitive, threat assumptions and receiving,
which P1 does not need.

## Private root and ordinary ancestors (A2.3)

- From the supplied root down to the leaf's parent, every directory must be a directory owned by
  `uid` with `mode & 0o7777` exactly 0o700. Setuid, setgid and sticky bits are not masked away.
- The leaf must be a regular file owned by `uid`, with exactly the required mode (0o600 on the
  private route, the supplied `mode` on the release route) and `nlink == 1`.
- Ancestors above the root (`/` down to the root's parent) are ordinary system directories. They
  get the same no-follow precheck, flags and identity check, so a symlinked ancestor is refused,
  not followed. They are not held to 0o700 or to `uid`, and they are not stamped: an ordinary
  `/tmp` (1777) or home directory (0755) above a private root is fine.
- This strict root policy does not certify ordinary repository paths. A real release root that
  does not meet it refuses. No chmod, mount or copy workaround is part of this module or
  authorized by it.

## Bounded read and named identity (A2.4)

- The leaf's fstat size must be at most `cap` before anything is read, and must equal
  `byte_length`.
- The reader reads exactly `byte_length` bytes in a bounded loop. One more read must then return
  EOF, so growth refuses and never ends in a prefix success.
- The full pre-read and post-read fstat must be equal (dev, ino, size, mtime_ns, ctime_ns, mode,
  uid, nlink), and the leaf predicates are checked again.
- A final no-follow `fstatat` of the leaf's name must still name the same dev, ino and type. A
  vanished name is drift.
- The full SHA256 and the length of `raw` must equal the Ref.
- `recheck_files` repeats the whole walk and compares every stamp (each directory and the leaf),
  the bytes, the hash and the length. Equal bytes under a new inode are drift.

## What is not claimed

- Same-UID isolation is not claimed (`SAME_UID_EXCLUSION_NOT_CLAIMED`). Any process running as
  the same uid, or as root, can change these files at any moment: between the precheck and the
  open, during the read, or after it. The reader refuses the changes its observations show
  (identity, full stamps, final name, recheck). It does not prevent or lock out a same-uid writer,
  and a pass means only that the observations matched.
- Ownership and mode are observations, not authority. A file owned by `uid` with mode 0o600 is not
  thereby issued, reviewed or trusted. `uid` is the caller's statement of the expected owner, not a
  check of who is running.
- A file observation supplies no filesystem capability. Native admission (issuer and scope, the
  selected runtime's uid, namespace, mounts and grants, the QA publication cohort) is not
  exercised here and cannot be stubbed (ABI A0.1 and A7, L2).
- In the tests, owner, device, dev-number and exact-step race cases use test-local wrappers around
  single syscalls. They prove the reader's checks, not OS access control or same-UID isolation.

## Tests

`tests/test_architecture/test_ops_host_binding_files.py` builds every fixture itself, inside the
test's own temporary directory, and never reads a real publication or private root. Known clean
cases come first. Then every F1 row of the r4 case appendix has its own fault test (`_n`, with
its exact code) and its own clean twin (`_c`). The suite also includes:

- a filesystem-call spy around every entry point the module could reach (open and `io.open`,
  the stat family including `dir_fd` forms, reads, `scandir`/`listdir`, `realpath` and the
  `os.path` helpers, plus the mutating, exec and spawn calls of `os`), used for every zero-calls
  assertion. F1-ARG-READS-LATER's clean twin shows the same spy counting the recheck's calls;
- FIFO cases under a hard timeout, where a timeout fails the test, and a bite that removes
  `O_NONBLOCK` to show the timeout really fires;
- check-disable bites for the digest, full-stamp and final-name checks;
- a descriptor-leak check after every test (descriptors on `/`, the test directory's ancestors
  or anything under it, which is every node the reader can open there), and a raw-sentinel check
  of repr, str, refusals and output.

Run: `uv run --quiet pytest -q tests/test_architecture/test_ops_host_binding_files.py`
