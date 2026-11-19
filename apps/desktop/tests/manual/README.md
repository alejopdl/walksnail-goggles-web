# Manual / live-hardware scripts

These are NOT pytest modules — they run top-to-bottom against real goggles
(via the adb phone tunnel) and print a ✅/❌ report:

    python tests/manual/integration_live.py

They live outside pytest's `test_*.py` glob on purpose: importing them
executes network calls.
