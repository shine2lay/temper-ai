# Run-owned W1 input for Project 3 controls

Architecture #351, requested integration for #125. Accountable lead: Architecture.
This changes transport, not W1 validation, browser admission or the history root.

## H-125-W1-INPUT-2 (before edits)

Evidence: Temper rm-ff4055ad reports the installed script image as UID/GID999
and the host worker as UID/GID1000. The existing optional `w1_before` string
carries a path and digest, not bytes. No runtime EACCES or future PID identity
has been observed. The selected bounded change stages the operator's exact
supplied bytes as the current process identity, then supplies the ordinary
reference to the unchanged W1 checker. Baseline: b70deeb7ba36db79763cd5e0b753ffcbc0eb212c;
the relevant existing paths match integrated 0bb9ff880ddcaef7c44d2a1d727564c2f306516a.

Expected measurements: byte-identical non-ASCII/newline and 65536-byte inputs;
0600 file/current effective UID/GID at the single fixed destination; the actual
W1 loader accepts a clean synthetic reading and rejects a schema-invalid one;
all malformed inline transports and unsafe paths/collisions stop before checker
launch; existing argv, output values and timeouts remain intact. Fixed negative
cases cover duplicate/extra/mixed keys, types, digest/base64/size errors,
symlinks in ancestors or leaf, wrong kinds, unsafe staging directory, existing
file/directory and a write/fsync error. Privacy canaries must be absent from
script stdout/stderr, run.log, returned metadata and checker child environment;
the ordinary input/event copy is expected and must remain disclosed.

Falsifiers: changed bytes/legacy diagnostics, accepted invalid transport,
checker launch on refusal, overwrite/repair/fallback, leaked payload in a new
output sink, failure of the real ScriptAgent transport at the allowed size, or
source/local tests misreported as installed UID999 qualification. A miss needs
a specific repair hypothesis or named dependency, not a blind full-suite rerun.
Result: first focused campaign 569/571 passed. The two `stage-public` cases
missed their intended boundary: the campaign's private umask turned their
requested 0755 test directory into 0700, so they supplied a compatible private
directory. The production path did not encounter an unsafe directory in those
cases. Source review and normal gates remain pending. No real reading,
workflow, helper or browser is run by this task.

### H-125-W1-INPUT-3: make the unsafe-directory fixture reach its boundary

Evidence: both failures are `stage-public`; `mkdir(mode=0755)` is filtered by
the campaign's umask 0077. Change only this synthetic fixture's creation: save
the test process umask, set zero just for mkdir, restore it immediately, then
assert the created directory is actually 0755 before calling transport. This
is test setup, not chmod/repair of an existing directory or a production
permission workaround. Expected: those cases refuse with no checker contact
and no path changes, and the affected transport/regression campaign passes.
Falsifier: actual 0755 survives staging or the setup itself fails. Result:
HIT: the affected transport and legacy wiring files pass 237/237; both actual
0755 cases now refuse at their intended boundary. The earlier campaign's 334
unchanged W1/admission/safety cases passed. Maximum-size real local
ScriptAgent/Bash transport, W1 validation, current UID/GID/0600 and privacy
checks pass; no installed UID999 or browser qualification is claimed.
No checker/W1/guard or frozen fixture source is changed.

## Interface and compatibility

`first_app_check` keeps the same optional **string** input `w1_before` and its
existing input map/environment route. Only `mode=controls_p3` accepts a nonblank
value. Omitted/null/empty/blank values and other modes retain their old behavior.

- Legacy JSON text `{path, sha256}` is forwarded byte-for-byte as the existing
  `--w1-before` argument. Non-inline values, including malformed JSON, still
  reach the old parser and retain its diagnostics.
- An object containing `data_base64` selects inline transport. It must have
  exactly `data_base64` and `sha256`, with no duplicate keys. Values must be
  strings: canonical standard base64 (no whitespace, URL alphabet, alternate
  padding or unused pad bits) and 64 lowercase hex characters. Mixed `path`
  plus bytes, extra keys and incorrect digests refuse before file creation.
- The existing W1 `READING_MAX=65536` bounds decoded bytes; its derived base64
  bound is 87384 characters. The supplied SHA256 is checked before writing.
  Neither the reading nor its timestamps/fields are reserialized or repaired.

`first_app_p3_w1_input.py` is transport only. It reuses
`first_app_p3_guard.directory_fd` and `write_private`, and imports the W1 size
bound. It never opens a host source path. Its destination is always the current
workspace's `check/w1-input/before.json`, created exclusively at 0600 by the
current process. The staging directory is 0700/current effective UID; unsafe
preexisting directories, symlinks, wrong kinds, collisions and I/O errors
refuse without chmod/chown/overwrite/unlink/alternate name or invocation retry.
The existing writer's mode-setting applies only to its own newly created file.
Partial evidence remains after failure. The reference then goes through the
unchanged W1 loader, schema/engine/freshness gate, history admission and stop rules.

Successful inline staging adds optional workflow output `w1_input_staging`:
fixed absolute `path`, supplied `sha256`, `process_uid`, `process_gid`, observed
`file_uid`, `file_gid`, and `file_mode`. It is absent/null for legacy calls. All
previous output values remain unchanged. Metadata is an ordinary observation,
not caller authentication, custody authority or hostile-same-UID exclusion.

## Privacy and authority

**This is not secret transport.** ScriptAgent._record_script_started records
`input_data`, including the inline envelope, on ordinary workflow input/event
surfaces. Base64 is encoding, not secrecy. Those records have normal retention;
private staging and removal of the inline input's environment slot before
checker launch neither delete them nor promise secure erasure. The script log
stores output, not its environment. No broader retention/destruction rule or
blanket log scrubber is introduced. Existing checker outputs are unchanged.

The trusted operator must already have authority for the exact reading AND its
ordinary workflow input/event storage boundary. A path or digest grants no
read authority. Source approval is not real-input consent. If that boundary is
not covered, return the specific custody/retention decision to Architecture;
do not fetch the original or use a permissions/privileged-copy workaround.

## Synthetic-only example

The bytes below are exactly `{}\n`. They intentionally fail the W1 reading
schema: this demonstrates transport, not a usable reading or start clearance.
The operator's actual input must encode its own already-authorized fresh
`webkit-reading/1` bytes without normalization. A local construction example:

```python
import base64
import hashlib
import json

synthetic_bytes = b"{}\n"
inputs = {
    "mode": "controls_p3",
    "w1_before": json.dumps({
        "data_base64": base64.b64encode(synthetic_bytes).decode("ascii"),
        "sha256": hashlib.sha256(synthetic_bytes).hexdigest(),
    }),
}
```

The exact synthetic workflow input is:

```json
{"mode":"controls_p3","w1_before":"{\"data_base64\":\"e30K\",\"sha256\":\"ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356\"}"}
```

No run is requested by this example. #125 performs the actual installed UID999
handoff and original clean control under its existing authority after delivery.
Local tests use the test process's actual UID, not UID999. Tests exercise real
WorkflowConfig, `_resolve_inputs`, ScriptAgent rendering, local Bash execution,
private writer and W1 reader; the checker execution boundary is explicitly a
synthetic stand-in. No browser/helper/workflow/Docker/model call qualifies here.

## Retained conditions

Security #184 accepts only its exact earlier source and fixtures. This delta
needs the normal exact-source review including the new input/event surface,
normal repository gates and actual delivered-source binding. #125 still owns
fresh execution readings, W1 before/after/finalize and original control scope.
W4/DECISION-9(b), the independent W1 gate even on empty history, A6 and
unconfirmed-cleanup all-browser stop remain. R1 is limited reporting; R2 is
unchosen. Host writes remain off/UNQUALIFIED; all owner/source/start holds and
frozen QA/spec/fixture bytes remain unchanged.
