# watch-stop: a box watch's STOP cancels the Project

A team Project can stay open for days, and nobody reads the box watch's records
all day. `scripts/pi_watch_stop.py` does: when the watch says STOP, or can't
check, it cancels the Project's run at once. The watch itself stays detection
only; this reader is the part that acts.

## What it reads

The watch writes one JSON file per check into its records folder. The reader
polls that folder (every 2 s) and reads each new top-level `*.json` once. Names
starting with `.` and anything in a subfolder are left alone. It only reads: it
never writes, moves or deletes anything there.

The fields it uses:

| field | use |
|---|---|
| `checked_at` | UTC time of the check; records before `--since` are logged, never acted on (no date: the file's time) |
| `verdict` | `PASS`, `STOP` or `COULD NOT CHECK`; anything other than exactly `PASS` acts |
| `kind`, `subject` | what was checked (`box` and the box name, `host-look`, `pins`, `watch`); older records have `box.name` instead, else the file name |
| `reasons` | the first one is the headline, and goes into the cancel reason |
| `notes` | never act, whatever they say (a `--quiet-notes` finding is a note) |

It fails closed. Each of these also counts as COULD NOT CHECK and cancels:

- a record that still doesn't parse when read again 2 s later;
- the watch's own user unit (`--watch-unit`) other than `active` for over 60 s
  in a row (a restart shows `activating` for a few seconds, which is fine);
- the records folder becoming unreadable.

So when the watch reaches its armed end while the Project is still open, the
Project ends a minute later. That's on purpose: extend the watch first.

Every start reads the folder again from `--since` (when the watch was armed for
this Project), so a reader that was down still acts on a STOP written meanwhile.

## What it does

The run's ordinary cancel, the same as the owner's Stop: `POST
/api/runs/<run>/cancel` with a reason, under its own named key `watch-stop`
([api-access.md](api-access.md)). Every member box stops and the records are
kept. The reason reads

    Security watch <verdict>: <kind> <subject>: <first reason>

(`<kind>` once when the subject is the kind itself, as for `pins`), cut to the
route's 2000 characters. The reader has no Telegram of its own: the owner hears
through the run's own `finished` notice, so the Project's start body sends that
notice to him.

Then it exits:

| exit | when | under the unit |
|---|---|---|
| 0 | the cancel was answered: cancelling, or the run had already ended (a second cancel is harmless) | stays stopped |
| 1 | the cancel kept failing (no answer, 5xx, a refused key) for 60 s, tried every 5 s | starts again after 5 s; the replay tries again |
| 2 | bad settings: no such folder, no key, a time without a zone | stays failed |
| 3 | the server has no such run (404) | stays failed |

**Trade-off, accepted for now:** a cancelled team run can't be resumed today,
so a false STOP ends the Project. A STOP means member isolation may be broken,
and the first trial had none (every box and host check passed). A hold that
can be resumed may come later.

## Running it

One Project at a time: the run id and the folder are settings, not code.

The key, once (never printed; the server re-reads its keys file, no restart):

    python3 scripts/api_key.py add watch-stop    # -> ~/.config/temper/api-keys/watch-stop.key (600)

At the Project's start, after the watch is armed and the run has started, write
`~/.config/temper/watch-stop.env` (600):

    RUN=<run id>
    SINCE=<when the watch was armed, UTC, e.g. 2026-10-09T17:00:00Z>
    RECORDS=<the watch's records folder, absolute>
    WATCH_UNIT=<the watch's user unit, if not security-trial-watch>

Then install and start the unit (`scripts/systemd/temper-watch-stop.service`;
enabled, it comes back after a reboot):

    install -m 0644 ~/temper-ai/scripts/systemd/temper-watch-stop.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now temper-watch-stop.service
    systemctl --user status temper-watch-stop.service      # active (running)
    journalctl --user -u temper-watch-stop -n 20           # "watching ... for run <id>", each record read

When the Project ends, before the watch is disarmed:

    systemctl --user disable --now temper-watch-stop.service

A dry run by hand: a folder of its own, a made-up run id, one STOP record. It
logs the record and one cancel answered 404, and exits 3:

    python3 scripts/pi_watch_stop.py --records /abs/dry-folder --run no-such-run \
        --since 2026-10-09T17:00:00Z --key-file ~/.config/temper/api-keys/watch-stop.key

Its test, `tests/test_scripts/test_pi_watch_stop.py`, runs the real script
against a stub cancel route and a stub `systemctl`.
