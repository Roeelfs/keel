# Test TMPDIR

The heavy lock defaults external test storage ON for the executable classes
`wt-verify.sh` and `cynap-sandbox` only. Set `KEEL_TEST_TMPDIR_ENABLED=0` to
disable it. Other classes retain their caller's environment, even with an
explicit enable. Normal, nested-lease and broker launches use the same adapter.

`tooling/harness/test_tmpdir.py` is the single selector. The sandbox runtime uses
it through the relative `keel_test_tmpdir.py` symlink; the resource-hooks installer
packages that same source for standalone runtime installs. No runtime install is
performed by editing these files.

Selection requires `/Volumes/T9` to be mounted, a private owner-only directory
(mode 0700), and a successful real file create and delete probe. An unmounted,
unwritable, unsafe or detached volume silently preserves the caller's internal
TMPDIR; storage selection never refuses the command. An inherited T9 TMPDIR is
replaced with the system's internal temporary directory. Selection happens at
startup; detaching the disk during a running test is not recoverable.

The standalone wrapper remains opt-in (`KEEL_TEST_TMPDIR_ENABLED=1`):

```sh
python3 tooling/harness/test_tmpdir.py -- <test command> [args...]
```

Measure the internal disk without probing or writing T9:

```sh
python3 tooling/harness/tmpdir_latency.py --files 2000
```

To measure the current external comparison, run:

```sh
python3 tooling/harness/tmpdir_latency.py --files 2000 --external
```

Both create/write/close and delete p99 must be at most twice the internal p99.
The probe uses 1–4 KiB files, no fsync, and removes its scratch directory. A failed
or omitted measurement leaves the gate `UNVERIFIED`; a slow result is `FAIL`.

The accepted machine latency gate is `PASS`: create/delete p99 ratios were
0.60/0.77, both below the 2x limit. This enables the heavy-lock defaults above;
it does not change the standalone wrapper's opt-in default.

The existing machine-local disk-keeper schedule can run the external fixture
helper without a new launchd job. Append this after its internal cleanup rules,
substituting the stable checkout path:

```sh
. "<checkout>/tooling/harness/disk-keeper-tmpdir.env.sh"
disk_keeper_external_fixtures
```

Keep the existing internal rules and do not set `DK_LEAK_ROOT` globally: it
replaces a legacy internal root. If it is already set, invoke the helper in a
subshell with `DK_LEAK_ROOT` unset so it selects the external default.
The helper cleans only owned directories matching its three fixture prefixes,
older than two hours, without following symlinks. Sourcing alone does no cleanup.
This repository change does not edit the machine-local disk-keeper or launchd;
the schedule hookup must be applied separately where machine-local writes are
permitted. No new schedule is needed.

Run the harness tests with Python's unittest runner:

```sh
python3 -m unittest discover -s tooling/harness -p 'test_*.py' -v
```
