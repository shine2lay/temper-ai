# watch-stop: a box watch's STOP cancels the Project

A team Project can stay open for days, and nobody reads the box watch's records
all day. `scripts/pi_watch_stop.py` does: when the watch says STOP, or can't
check, it cancels the Project's run at once. The watch itself stays detection
only; this reader is the part that acts.

## What it reads

The watch writes one JSON file per check into its records folder. The reader
polls that folder (every 2 s) and reads each new top-level regular `*.json` file
once. Dot-names, subfolders, symlinks and other file types are left alone. It only reads: it
never writes, moves or deletes anything there.

The fields it uses:

| field | use |
|---|---|
| `checked_at` | Full UTC datetime of the check; records before `--since` are logged, never acted on (missing, date-only, numeric, naive or otherwise unusable time: the file's mtime) |
| `verdict` | `PASS`, `STOP` or `COULD NOT CHECK`; anything other than exactly `PASS` acts |
| `kind`, `subject` | what was checked (`box` and the box name, `host-look`, `pins`, `watch`); older records have `box.name` instead, else the file name |
| `reasons` | the first one is the headline, and goes into the cancel reason |
| `notes` | never act, whatever they say (a `--quiet-notes` finding is a note) |
| `gap_from`, `gap_to` | UTC bounds of a `watch` / `continuity` gap; missing or invalid bounds use `--since` and `checked_at` respectively |

It fails closed. Each of these also counts as COULD NOT CHECK and cancels:

- a record that still doesn't parse when read again 2 s later, including a
  record over 1 MiB or with JSON nesting deeper than 64 levels;
- the watch's own user unit (`--watch-unit`) other than `active` for over 5 min
  in a row (the grace allows Docker to come back after a reboot);
- the records folder becoming unreadable.

So when the watch reaches its armed end while the Project is still open, the
Project ends five minutes later. That's on purpose: extend the watch first.

Every start reads the folder again from `--since`: the UTC timestamp when the
Project's open word was sent to Security. Fix that timestamp for the whole
Project, including reader restarts and watch re-arms; never advance it to a
later arming or reader-start time. A reader that was down still acts on a STOP
written meanwhile. Retain all records since that boundary until the Project
ends; the reader keeps processed names in memory and rescans them after a restart.

### A continuity gap after a restart

Only `kind: watch`, `subject: continuity`, `verdict: COULD NOT CHECK` gets this
check instead of an immediate cancel. Docker's short events history may not
cover a watch restart; ending the Project on that fact alone would prevent its
normal recovery after a reboot.

Under its named key, the reader asks `GET /api/team/runs/<run>/boxes` for every
turn's box name, turn id, start and end times and creation evidence. The reader
never connects to the database. Every named box whose turn started at or before
`gap_to` and ended at or after `gap_from` (or has not ended) needs a `kind: box`,
`subject: <exact box name>`, `verdict: PASS` record from this Project. This
includes boxes that ended before the reader came back. Only a final worker
receipt explicitly saying the container was never created exempts a turn;
missing or uncertain evidence does not. The API does not treat an older
`created: false` receipt as proof: it can also follow a Docker-create timeout.
Without explicit evidence that no creation was attempted, that box needs PASS.

All accounted for: log it and carry on. A missing PASS, an unreadable API reply,
or a turn time that cannot be checked: read new records and ask the API once
more after 10 s (`--continuity-wait`), then cancel if still unproven. API times
must include a zone, and replies larger than 16 MiB count as unreadable. A missing
box's reason is:

    Security watch COULD NOT CHECK: watch continuity: <box> has no PASS record

Every other non-PASS still acts at once, including a box's STOP or COULD NOT
CHECK, even while the continuity check waits. Notes cannot excuse a gap.

## What it does

The run's ordinary cancel, the same as the owner's Stop: `POST
/api/runs/<run>/cancel` with a reason, under its own named key `watch-stop`
([api-access.md](api-access.md)). Member cleanup belongs to that ordinary engine
cancel path; the reader's HTTP receipt alone is not physical-stop proof. Records
are kept. The reason reads

    Security watch <verdict>: <kind> <subject>: <first reason>

(`<kind>` once when the subject is the kind itself, as for `pins`), cut to the
route's 2000 characters. The reader has no Telegram of its own: the owner hears
through the run's own `finished` notice, so the Project's start body sends that
notice to him. Record-derived text is escaped onto one line before logging or
sending it. The key is validated without printing its contents, and HTTP
redirects and proxies are disabled for both cancel and box-evidence reads;
only the configured server is called.

Then it exits:

| exit | when | under the unit |
|---|---|---|
| 0 | the cancel was answered: cancelling, or the run had already ended (a second cancel is harmless) | stays stopped |
| 1 | the cancel kept failing (no answer, 5xx, a refused key) for 60 s, tried every 5 s | starts again after 5 s; the replay tries again |
| 2 | bad settings: relative records path, no key, a time without a zone | stays failed |
| 3 | the server has no such run (404) | stays failed |

**Trade-off, accepted for now:** a cancelled team run can't be resumed today,
so a false STOP ends the Project. A STOP means member isolation may be broken,
so ending the run is safer than continuing unchecked. A hold that can be
resumed may come later.

## Running it

One Project at a time: the run id and the folder are settings, not code.

The key, once (never printed; the server re-reads its keys file, no restart):

    python3 scripts/api_key.py add watch-stop    # -> ~/.config/temper/api-keys/watch-stop.key (600)

At the Project's start, after the watch is armed and the run has started, write
`~/.config/temper/watch-stop.env` (600):

    RUN=<run id>
    SINCE=<fixed open-word timestamp, UTC, e.g. 2026-10-09T17:00:00Z>
    RECORDS=<the watch's records folder, absolute>
    WATCH_UNIT=<the watch's user unit, if not security-trial-watch>

Then install and start the unit (`scripts/systemd/temper-watch-stop.service`;
enabled, it comes back after a reboot):

    install -m 0644 ~/temper-ai/scripts/systemd/temper-watch-stop.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now temper-watch-stop.service
    systemctl --user status temper-watch-stop.service      # active (running)
    journalctl --user -u temper-watch-stop -n 20           # "watching ... for run <id>", each record read

Check that the current journal's `watching` line names the correct RUN and
fixed SINCE, not just that the unit is enabled. Do not allow the Project to
proceed after a setup failure. Correct the settings, then `systemctl --user
restart temper-watch-stop.service` and check its new journal. `enable --now`
does not reload settings in an already-running reader. Keep checking reader
health during the open period; reboot behavior is configured, not live-tested
by the script's test.

When the Project ends, before the watch is disarmed:

    systemctl --user disable --now temper-watch-stop.service

A dry run by hand: a folder of its own, a made-up run id, one STOP record. It
logs the record and one cancel answered 404, and exits 3:

    python3 scripts/pi_watch_stop.py --records /abs/dry-folder --run no-such-run \
        --since 2026-10-09T17:00:00Z --key-file ~/.config/temper/api-keys/watch-stop.key

Its test, `tests/test_scripts/test_pi_watch_stop.py`, runs the real script
against a stub cancel route and a stub `systemctl`.
