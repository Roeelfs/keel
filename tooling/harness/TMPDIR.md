# Optional test TMPDIR

The switch is off by default. Run tests with the caller's internal TMPDIR:

```sh
python3 tooling/harness/test_tmpdir.py -- <test command> [args...]
```

After the latency gate passes on the current machine, opt in for a command with
`KEEL_TEST_TMPDIR_ENABLED=1`. The wrapper selects a private, owner-only directory
on `/Volumes/T9` only when the volume is mounted and a real file create and delete
succeed. A failed probe silently preserves the internal TMPDIR. An inherited T9
TMPDIR is replaced with the system's internal temporary directory. Selection
happens at startup; detaching the disk during a running test is not recoverable.

Measure the internal disk without probing or writing T9:

```sh
python3 tooling/harness/tmpdir_latency.py --files 2000
```

Once the volume owner restores T9 write access, run the comparison:

```sh
python3 tooling/harness/tmpdir_latency.py --files 2000 --external
```

Both create/write/close and delete p99 must be at most twice the internal p99.
The probe uses 1–4 KiB files, no fsync, and removes its scratch directory. A failed
or omitted measurement leaves the gate `UNVERIFIED`; a slow result is `FAIL`.
Even `PASS` leaves the switch default off: opt in explicitly after inspecting it.

The internal-only run on 2026-11-07 measured 2,000 files: create p99 228.084 µs,
delete p99 134.333 µs. T9 was not measured; its gate remains `UNVERIFIED`, pending
restored write access and the comparison above.

For optional fixture cleanup, source `disk-keeper-tmpdir.env.sh` after the normal
internal disk-keeper rules and explicitly call `disk_keeper_external_fixtures`.
It cleans only owned directories matching the three listed fixture prefixes,
older than two hours, without following symlinks. Sourcing alone does no cleanup
and does not install a schedule or enable the switch.

Run the harness tests with Python's unittest runner:

```sh
python3 -m unittest discover -s tooling/harness -p 'test_*.py' -v
```
