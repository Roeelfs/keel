#!/usr/bin/env python3
"""Disposable small-file comparison; no fsync (matches ordinary fixture writes).

Usage: python3 tooling/harness/tmpdir_latency.py [--files 2000]
Print JSON to stdout; failed measurements never authorize the external switch.
Only a uniquely named probe directory is written on the external volume.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from time import perf_counter_ns


def percentiles(samples):
    ordered = sorted(samples)
    return {f"p{p}_us": ordered[math.ceil(len(ordered) * p / 100) - 1] / 1000
            for p in (50, 99)}


def measure(root, count):
    try:
        with tempfile.TemporaryDirectory(prefix="keel-latency-", dir=root) as scratch:
            paths = tuple(Path(scratch) / str(i) for i in range(count))
            payloads = tuple(b"x" * size for size in (1024, 2048, 3072, 4096))
            creates, deletes = [], []
            for i, path in enumerate(paths):
                start = perf_counter_ns()
                path.write_bytes(payloads[i % 4])
                creates.append(perf_counter_ns() - start)
            for path in paths:
                start = perf_counter_ns()
                path.unlink()
                deletes.append(perf_counter_ns() - start)
        return {"status": "measured", "files": count, "create": percentiles(creates),
                "delete": percentiles(deletes), "probe_files_removed": True}
    except OSError as error:
        return {"status": "blocked", "error": str(error)}


def compare(internal, external):
    if any(result["status"] != "measured" for result in (internal, external)):
        return {"gate": "UNVERIFIED", "switch_default": "off"}
    ratios = {op: external[op]["p99_us"] / internal[op]["p99_us"]
              for op in ("create", "delete")}
    return {"gate": "PASS" if max(ratios.values()) <= 2 else "FAIL",
            "p99_ratios": ratios, "switch_default": "off"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=2000)
    parser.add_argument("--external", action="store_true",
                        help="also measure T9; run only after write access is restored")
    args = parser.parse_args()
    if args.files < 1:
        parser.error("--files must be positive")
    # Do not trust an inherited TMPDIR that may already point to external storage.
    internal_root = subprocess.check_output(
        ["getconf", "DARWIN_USER_TEMP_DIR"], text=True).strip()
    external_root = Path("/Volumes/T9")
    internal = measure(internal_root, args.files)
    external = {"status": "not_run", "reason": "requires --external"}
    if args.external:
        external = (measure(external_root, args.files) if os.path.ismount(external_root)
                    else {"status": "blocked", "error": "external volume is not mounted"})
    print(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                      "method": "sequential create/write/close then unlink; 1-4 KiB; no fsync",
                      "internal": internal, "external": external,
                      **compare(internal, external)}, indent=2))


if __name__ == "__main__":
    main()
