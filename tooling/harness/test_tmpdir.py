#!/usr/bin/env python3
"""Run a test command with an optional external TMPDIR.

Usage: python3 tooling/harness/test_tmpdir.py -- <test command> [args...]
Default OFF: set KEEL_TEST_TMPDIR_ENABLED=1 only after both create/delete
p99 latency ratios pass the <=2 gate in tmpdir_latency.py on this machine.
The caller's internal TMPDIR is preserved on any failed volume probe.
Selection is a startup check: unplugging during a running test is not recoverable.
"""
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


VOLUME = Path("/Volumes/T9")


def private_root(volume):
    return volume / f"keel-test-tmp-{os.getuid()}"


def usable_root(root):
    info = root.lstat()
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700)


def internal_env(env, volume):
    """Discard an inherited external path even when the switch is disabled."""
    tmp = env.get("TMPDIR")
    if not tmp or not Path(os.path.abspath(tmp)).is_relative_to(volume):
        return dict(env)
    try:
        root = subprocess.check_output(
            ["getconf", "DARWIN_USER_TEMP_DIR"], text=True).strip()
        if root and not Path(os.path.abspath(root)).is_relative_to(volume):
            return {**env, "TMPDIR": root}
    except (OSError, subprocess.CalledProcessError):
        pass  # Non-macOS hosts use the conventional internal temporary root.
    return {**env, "TMPDIR": "/tmp"}


def command_env(env, volume=VOLUME):
    """Never create a mount-point stub; verify ownership and actual file I/O."""
    fallback = internal_env(env, volume)
    try:
        if (env.get("KEEL_TEST_TMPDIR_ENABLED") != "1" or volume.is_symlink()
                or not os.path.ismount(volume)):
            return fallback
        root = private_root(volume)
        root.mkdir(mode=0o700, exist_ok=True)
        if not usable_root(root):
            return fallback
        with tempfile.TemporaryDirectory(prefix=".writable-", dir=root) as probe:
            path = Path(probe) / "probe"
            path.write_bytes(b"writable")
            path.unlink()
        # Catch a detach during the write check before publishing the path.
        if not os.path.ismount(volume):
            return fallback
        return {**env, "TMPDIR": str(root)}
    except OSError:
        return fallback


def main():
    command = sys.argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise SystemExit("usage: test_tmpdir.py -- <test command> [args...]")
    os.execvpe(command[0], command, command_env(os.environ))


if __name__ == "__main__":
    main()
