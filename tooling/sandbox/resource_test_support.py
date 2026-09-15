"""Fixture-only entrypoints for resource-runner subprocess tests."""
import os
from pathlib import Path


SANDBOX = Path(__file__).resolve().parent


HOOKS = SANDBOX.parents[1] / ".claude" / "hooks"


def isolated_wrapper(home, setup=""):
    """Create a test executable that replaces account_home (and any `setup` stubs) before runner import."""
    home = Path(home)
    wrapper = home / "with-heavy-lock"
    wrapper.write_text(
        "#!%s\n"
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, %r)\n"
        "import heavy_resources\n"
        "heavy_resources.account_home = lambda: Path(%r)\n"
        "%s"
        "import heavy_runner\n"
        "raise SystemExit(heavy_runner.main())\n"
        % (os.path.realpath(os.sys.executable), str(SANDBOX), str(home), setup),
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    return str(wrapper)


def isolated_hook(home):
    """Create a test executable that runs the resource hook against a fixture account home."""
    home = Path(home)
    hook = str(HOOKS / "serialize-heavy-ops.py")
    shim = home / "resource-hook"
    shim.write_text(
        "#!%s\n"
        "import pwd, runpy, sys\n"
        "from types import SimpleNamespace\n"
        "sys.path.insert(0, %r)\n"
        "pwd.getpwuid = lambda _uid: SimpleNamespace(pw_dir=%r)\n"
        "sys.argv = [%r, *sys.argv[1:]]\n"
        "runpy.run_path(%r, run_name='__main__')\n"
        % (os.path.realpath(os.sys.executable), str(HOOKS), str(home), hook, hook),
        encoding="utf-8",
    )
    shim.chmod(0o700)
    return str(shim)
