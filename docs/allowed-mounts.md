# Final container bind checks

`temper_ai/spawner/allowed_mounts.py` checks the **finished Docker run/create arguments**,
not an earlier planned mount list. It owns parsing and mount permission checks, not
spawning, credentials, profiles or orchestration.

## Boundaries and declarations

| Execution boundary | Independent permission input | Preserved rules |
| --- | --- | --- |
| Legacy `DockerSpawner.spawn` | Inspected template's inherited binds, configured login-file bind, `WORKSPACE_DIR`, configured/default main-repository roots | Fixed source/target/read-only triples; own workspace at its existing host target, writable; separate E7 lexical, symlink and worktree-backlink validation for the main repository |
| Sealed `DockerSpawner._spawn_sealed` | Snapshot of `SealPlan.grants`, before command serialization | Exact grant source/target/read-only triples; existing pin/view/profile checks remain |
| `DockerSpawner._box_ids` uid probe | Empty host-bind policy | Image-only run; adding any host bind or indirect host-mount option refuses |
| Pi `WorkerBox.start` | Configured fixed destinations/modes and sealed-copy sources, before `create_args`; configured roots | Fixed triples plus the root fence; the existing public `mounts`, `_check_bind_sources`, `inside_roots` import and `bind_source_outside_roots` error remain |

`DockerSpawner._launch_container` calls the shared checker immediately before `_docker_run`.
Pi calls the same checker immediately before its create call. No argument additions follow
these checks in their execution paths. The earlier Pi check remains for callers using
`create_args` directly; it does not substitute for the final guard.

The one-shot delivery writer (`DockerSpawner._deliver`) uses **docker exec in the existing
sealed container**, not docker run/create. Exec does not accept new host mounts. The writer's
delivery envelope, credentials, deadlines and existing grants are unchanged. Pi's subsequent
docker start also uses its already-created container, not a new set of bind arguments.

The declarations are not derived from the completed argv or a request's `.git` contents.
A `.git` file selects a possible main repository only after an independent configured-root
fence; E7 still validates its form, lexical root, symlinks, visible record and backlink.
A root does not authorize arbitrary target/access changes, and cannot widen a fixed
read-only source into a new descendant bind. Legacy dynamic binds fail closed without the
required root declarations; sealed binds fail closed without their exact grants.

Pi's historical empty-roots standalone compatibility remains: no root containment check is
claimed in that case. The final fixed-declaration check still applies. The live Pi lane's
preflight still requires roots; it has not been removed or relaxed.

## Argument parsing

The parser consumes Docker option values and stops at the image (or Docker's `--` separator).
Mount-looking arguments in the container's command are not Docker mount options. Supported
bind forms include `--mount value`, `--mount=value`, `-v value`, `-vSOURCE:TARGET:MODE`,
`-v=SOURCE:TARGET:MODE`, `--volume value` and `--volume=value`, including Docker's source,
destination and read-only aliases. Existing non-host tmpfs/anonymous-volume forms are
recognized. Binds retain the ordinary private propagation behavior.

Unknown option arity, duplicate/contradictory fields or targets, malformed paths, unsupported
mount modifiers and unreadable syntax refuse rather than being silently skipped. Named
volumes, volume drivers, volumes-from and similar indirect host-mount inputs refuse: this
component has no independent declaration resolving them to host sources. This is deliberately
a parser for the engine's actual launch surface, not an implementation of every Docker flag.
A new launch option needs an explicit parser entry and test before use.

A refusal reports a named site and category, not the argv, environment values, credentials
or command payload. The legacy and sealed paths use their existing spawner/profile errors;
Pi uses its existing box-error surface. The historical Pi source-only method keeps its
existing destination-naming error for compatibility.

## Host namespace and limitations

Containment is canonical, including prefix boundaries, rather than a string-prefix check.
For legacy dynamic binds, the worker's **own inspected host-source/worker-target mapping**
is reused through `WorkerView.canonical_host_path`. Link text is interpreted in the host
namespace, then mapped back for inspection. A worker-only absolute alias is not treated as
a host path; invisible paths and mount-shadowed views refuse. Native host execution uses
local realpath. Sealed fixed grants keep their existing worker-view pins and readback.

Inspected bind roots are trusted namespace anchors. A container does not thereby gain a
view of those anchors' host ancestors. Pi's deployment already uses identity-mapped declared
roots; its local canonical check relies on that deployment invariant and is not independent
proof of a remote Docker daemon's filesystem. Configuring a different namespace requires
an actual supported mapping, not merely supplying more strings as roots.

This final check is **not a race-proof pin**. Mutable links can change between the check and
Docker's path lookup. Existing sealed pins/readback are not replaced, and E7's separate
checks are not replaced by realpath. Exact inherited template binds remain trusted inputs:
accepting them is not proof that their content, ancestors or inherited submounts are safe.

No cross-run ownership, private-root exclusion or containment of private data follows merely
from membership in broad configured roots. This component does not complete E8's private-root
condition or Security's C8, activate isolation, configure a private placement/grant, or admit
private data. Those require concrete placement/grant declarations and separate evidence,
including rejecting sources equal to, below **or above** the actual private root except its
designated grant.

## Evidence surface

`tests/test_spawner/test_final_bind_checks.py` opens with one combined caller happy path and
captures final argv at stubbed Docker boundaries. Negative cases mutate completed builders,
not just the earlier mount lists. `test_allowed_mounts.py` covers syntax, permission and
translated-namespace cases. `test_final_bind_inventory.py` scans the engine's Python sources,
checks the launch-site inventory, and classifies the writer as exec-only. Existing E7, Pi,
sealed, source-scan and full-gate coverage remains required. A green component test is not a
private-root, live-workflow or deployment proof.
