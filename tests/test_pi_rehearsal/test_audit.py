"""The Pi rehearsal rig's mount check and names-only box readings (scripts/pi_rehearsal/audit.py).

docker inspect's output is stood in by the fields the checks read; no Docker, nothing starts.
The mount check runs on created, never started, containers: every bind source must sit in the
rig's own tree, except pi-worker's Docker socket (PW02), and anything it can't place is a no.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .support import load

audit = load("audit")

PROJECT = "pi-rehearsal-0123abcd"
BOX = "temper-pi-0123456789abcdef0123"
SECRET = "do-not-copy-this-value"


def container(service: str, mounts: list[dict], *, status: str = "created",
              project: str = PROJECT) -> dict:
    return {"Name": f"/{project}-{service}-1", "State": {"Status": status}, "Mounts": mounts,
            "Config": {"Labels": {"com.docker.compose.project": project,
                                  "com.docker.compose.service": service}}}


def bind(source: Path | str, destination: str, *, rw: bool = False) -> dict:
    return {"Type": "bind", "Source": str(source), "Destination": destination, "RW": rw}


@pytest.fixture
def rig(tmp_path: Path) -> dict:
    """A rig tree with its checkout inside, and a Docker socket stand-in outside it."""
    root = tmp_path / "rig"
    checkout = root / "checkout"
    for folder in ("checkout/temper_ai", "checkout/configs", "workspaces", "state/runs",
                   "boxcfg", "standin", "share/pi-runtime", "ca", "sock/box1", "w/turn1"):
        (root / folder).mkdir(parents=True)
    (root / "ca/ca.pem").write_text("stand-in CA\n")
    socket = tmp_path / "docker.sock"
    socket.write_text("")
    outside = tmp_path / "home" / ".claude"
    outside.mkdir(parents=True)
    return {"root": root, "checkout": checkout, "socket": socket, "outside": outside}


def rig_containers(rig: dict) -> list[dict]:
    root, co = rig["root"], rig["checkout"]
    code = [bind(co / "temper_ai", "/app/temper_ai"), bind(co / "configs", "/app/configs")]
    return [
        container("postgres", [{"Type": "tmpfs", "Destination": "/var/lib/postgresql/data",
                                "Source": "", "RW": True}]),
        container("server", [*code, bind(root / "workspaces", str(root / "workspaces"), rw=True),
                             {"Type": "volume", "Name": f"{PROJECT}_cache", "Source": "/x",
                              "Destination": "/cache", "RW": True}]),
        container("pi-worker", [*code, bind(rig["socket"], "/var/run/docker.sock", rw=True),
                                bind(root / "state/runs", str(root / "state/runs"), rw=True),
                                bind(root / "boxcfg", str(root / "boxcfg"))]),
        container("standin", [bind(root / "standin", "/standin")]),
    ]


def check(rig: dict, containers: list[dict], **kw) -> dict:
    return audit.mount_check(containers, root=kw.get("root", rig["root"]),
                             checkout=kw.get("checkout", rig["checkout"]),
                             project=kw.get("project", PROJECT), docker_socket=rig["socket"])


def test_a_whole_rig_passes_with_every_mount_placed_before_anything_starts(rig):
    result = check(rig, rig_containers(rig))

    assert result["result"] == "pass" and result["before_start"] is True
    assert result["project"] == PROJECT
    placed = {(row["service"], row["destination"]): row for row in result["mounts"]}
    assert len(placed) == 11
    assert placed[("server", "/app/temper_ai")]["classification"] == "own checkout"
    assert placed[("server", "/app/temper_ai")]["read_only"] is True
    workspaces = placed[("server", str(rig["root"] / "workspaces"))]
    assert workspaces["classification"] == "rig scratch tree" and workspaces["read_only"] is False
    assert placed[("server", "/cache")]["classification"] == "own compose volume"
    assert placed[("postgres", "/var/lib/postgresql/data")]["classification"] == "throwaway tmpfs"
    assert placed[("pi-worker", "/var/run/docker.sock")]["classification"] == \
        "PW02: pi-worker Docker socket"
    assert {row["container"] for row in result["mounts"]} == {
        f"{PROJECT}-{s}-1" for s in ("postgres", "server", "pi-worker", "standin")}


def _outside(rig, cs):
    cs[3]["Mounts"].append(bind(rig["outside"], "/creds"))


def _socket_on_server(rig, cs):
    cs[1]["Mounts"].append(bind(rig["socket"], "/var/run/docker.sock", rw=True))


def _socket_elsewhere(rig, cs):
    cs[2]["Mounts"][2]["Destination"] = "/run/docker.sock"


def _link_out(rig, cs):
    link = rig["root"] / "standin" / "link"
    link.symlink_to(rig["outside"])
    cs[3]["Mounts"].append(bind(link, "/link"))


def _missing(rig, cs):
    cs[3]["Mounts"].append(bind(rig["root"] / "not-there", "/gone"))


def _relative(rig, cs):
    cs[3]["Mounts"].append(bind("standin", "/rel"))


def _started(rig, cs):
    cs[1]["State"]["Status"] = "running"


def _foreign_volume(rig, cs):
    cs[1]["Mounts"][-1]["Name"] = "temper-ai_pgdata"


def _foreign_container(rig, cs):
    cs.append(container("server", [], project="temper-ai"))


def _unknown_type(rig, cs):
    cs[3]["Mounts"].append({"Type": "npipe", "Source": "x", "Destination": "/p", "RW": True})


def _no_flag(rig, cs):
    del cs[3]["Mounts"][0]["RW"]


def _no_mount_list(rig, cs):
    cs[3]["Mounts"] = None


def _no_service(rig, cs):
    del cs[3]["Config"]["Labels"]["com.docker.compose.service"]


@pytest.mark.parametrize(("change", "why"), [
    (_outside, "bind source outside rig"),
    (_socket_on_server, "only pi-worker may mount docker.sock"),
    (_socket_elsewhere, "only pi-worker may mount docker.sock"),
    (_link_out, "bind source outside rig"),
    (_missing, "path can't be read"),
    (_relative, "unknown bind source"),
    (_started, "still created"),
    (_foreign_volume, "unclassified named volume"),
    (_foreign_container, "another compose project"),
    (_unknown_type, "unknown mount type"),
    (_no_flag, "no read-only flag"),
    (_no_mount_list, "unknown mount list"),
    (_no_service, "no compose service"),
])
def test_anything_it_cannot_place_is_a_refusal(rig, change, why):
    containers = rig_containers(rig)
    change(rig, containers)
    with pytest.raises(audit.RigRefusal, match=why):
        check(rig, containers)


def test_the_rig_itself_must_be_a_rehearsal_project_holding_its_checkout_and_not_home(
        rig, tmp_path, monkeypatch):
    containers = rig_containers(rig)
    with pytest.raises(audit.RigRefusal, match="not a rehearsal compose project"):
        check(rig, containers, project="temper-ai")
    with pytest.raises(audit.RigRefusal, match="checkout must be inside"):
        check(rig, containers, checkout=rig["outside"])
    with pytest.raises(audit.RigRefusal, match="no created containers"):
        check(rig, [])
    monkeypatch.setenv("HOME", str(rig["root"] / "state"))
    with pytest.raises(audit.RigRefusal, match="holds the home folder"):
        check(rig, containers)


# ------------------------------------------------------------------- names-only box readings


def member(rig: dict, **host) -> dict:
    root = rig["root"]
    return {
        "Name": f"/{BOX}", "Image": "sha256:" + "a" * 64,
        "Config": {"User": "1000:1000",
                   "Env": [f"PI_TOKEN={SECRET}", "NODE_EXTRA_CA_CERTS=/box-ca/ca.pem", "HOME=/w"],
                   "Labels": {"temper.pi.box": "1", "temper.pi.run": "run-1",
                              "temper.pi.turn": "turn-1"}},
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                       "CapAdd": None, "CapDrop": ["ALL"], "Devices": None, "PidMode": "",
                       "IpcMode": "private", "UsernsMode": "",
                       "SecurityOpt": ["no-new-privileges"], **host},
        "NetworkSettings": {"Networks": {"none": {}}},
        "Mounts": [bind(root / "share/pi-runtime", "/pi-runtime"),
                   bind(root / "ca/ca.pem", "/box-ca/ca.pem"),
                   bind(root / "w/turn1", "/w", rw=True),
                   bind(root / "sock/box1", "/box-sock")],
    }


def settings(rig: dict) -> dict[str, str]:
    root = rig["root"]
    return {"runtime_dir": str(root / "share/pi-runtime"), "rehearsal.ca_pem": str(root / "ca/ca.pem"),
            "state_root": str(root / "w"), "socket_root": str(root / "sock"),
            "host_helper_socket": str(root / "helper/host.sock")}


def test_a_member_box_reading_names_everything_and_holds_no_value(rig):
    out = audit.names_only(member(rig), settings=settings(rig), root=rig["root"], member=True)

    assert SECRET not in json.dumps(out)
    assert out["env_names"] == ["HOME", "NODE_EXTRA_CA_CERTS", "PI_TOKEN"]
    assert out["rehearsal_only_env_names"] == ["NODE_EXTRA_CA_CERTS"]
    assert out["name"] == BOX and out["run_id"] == "run-1" and out["turn_id_prefix"] == "turn-1"
    assert (out["network_mode"], out["read_only_root"], out["privileged"]) == ("none", True, False)
    assert (out["cap_add"], out["cap_drop"], out["devices"]) == ([], ["ALL"], [])
    assert out["security_options"] == ["no-new-privileges"] and out["user"] == "1000:1000"
    mounts = {m["destination"]: m for m in out["mounts"]}
    assert mounts["/pi-runtime"]["settings"] == ["runtime_dir"] and mounts["/pi-runtime"]["read_only"]
    assert mounts["/box-ca/ca.pem"]["rehearsal_only"] is True
    assert mounts["/box-ca/ca.pem"]["settings"] == ["rehearsal.ca_pem"]
    assert mounts["/w"]["read_only"] is False and mounts["/w"]["settings"] == ["state_root"]
    assert mounts["/box-sock"]["settings"] == ["socket_root"]
    assert [m["rehearsal_only"] for m in out["mounts"]].count(True) == 1


def _rename(rig, box):
    box["Name"] = "/temper-pi-run-1"


def _bridge(rig, box):
    box["HostConfig"]["NetworkMode"] = "bridge"


def _cap(rig, box):
    box["HostConfig"]["CapAdd"] = ["NET_ADMIN"]


def _writable_root(rig, box):
    box["HostConfig"]["ReadonlyRootfs"] = False


def _privileged(rig, box):
    box["HostConfig"]["Privileged"] = True


def _device(rig, box):
    box["HostConfig"]["Devices"] = [{"PathOnHost": "/dev/fuse"}]


def _docker_socket(rig, box):
    socket = rig["root"] / "w" / "docker.sock"
    socket.write_text("")
    box["Mounts"].append(bind(socket, "/var/run/docker.sock"))


def _helper_socket(rig, box):
    (rig["root"] / "helper").mkdir()
    (rig["root"] / "helper/host.sock").write_text("")
    box["Mounts"].append(bind(rig["root"] / "helper/host.sock", "/host.sock"))


def _outside_bind(rig, box):
    box["Mounts"].append(bind(rig["outside"], "/creds"))


def _unnamed_bind(rig, box):
    box["Mounts"].append(bind(rig["root"] / "standin", "/standin"))


@pytest.mark.parametrize(("change", "why"), [
    (_rename, "not a real WorkerBox name"),
    (_bridge, "unexpected isolation"),
    (_cap, "unexpected isolation"),
    (_privileged, "unexpected isolation"),
    (_device, "unexpected isolation"),
    (_writable_root, "root or capabilities"),
    (_docker_socket, "Docker socket"),
    (_helper_socket, "helper socket"),
    (_outside_bind, "outside rig scratch tree"),
    (_unnamed_bind, "no box-setting classification"),
])
def test_a_member_box_outside_the_box_rules_is_refused(rig, change, why):
    box = member(rig)
    change(rig, box)
    with pytest.raises(audit.RigRefusal, match=why):
        audit.names_only(box, settings=settings(rig), root=rig["root"], member=True)


def test_service_readings_are_names_only_without_the_member_rules(rig):
    service = member(rig, NetworkMode=f"{PROJECT}_rig", CapAdd=None)
    service["Name"] = f"/{PROJECT}-pi-worker-1"
    service["Mounts"].append(bind(rig["socket"], "/var/run/docker.sock", rw=True))

    out = audit.names_only(service, settings=settings(rig), root=rig["root"])

    assert out["name"] == f"{PROJECT}-pi-worker-1" and SECRET not in json.dumps(out)
    assert {m["destination"] for m in out["mounts"]} >= {"/var/run/docker.sock", "/pi-runtime"}


def test_bind_settings_name_a_shared_root_both_ways():
    named = {"add_ons.pi-tldr.dir": "/rig/share/addons/pi-tldr", "runtime_dir": "/rig/share/rt"}
    assert audit.bind_settings("/rig/share", named) == ["add_ons.pi-tldr.dir", "runtime_dir"]
    assert audit.bind_settings("/rig/share/rt/bin", named) == ["runtime_dir"]
    assert audit.bind_settings("/rig/other", named) == []
