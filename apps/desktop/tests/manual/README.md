# Manual / live-hardware scripts

These are NOT pytest modules — they run top-to-bottom against real goggles
(via the adb phone tunnel on `127.0.0.1:18080`) and print a ✅/❌ report.
Run from `apps/desktop`:

    python tests/manual/integration_live.py                   # read-only
    python tests/manual/integration_live.py --allow-settime   # also syncs the clock

By default the script only reads from the goggles: it sends no command that
changes them, and steps that would are reported as skipped.

| Flag | What it adds |
|---|---|
| `--allow-settime` | Sets the goggles clock to this computer's time, once, through `POST /api/settime`. Not retried if the reply is lost. |

They live outside pytest's `test_*.py` glob on purpose: importing them
executes network calls.
