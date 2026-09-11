"""Fixture-only entrypoints for resource-runner subprocess tests."""
import os
from pathlib import Path


SANDBOX = Path(__file__).resolve().parent


def isolated_wrapper(home):
    """Create a test executable that replaces account_home before runner import."""
    home = Path(home)
    wrapper = home / "with-heavy-lock"
    wrapper.write_text(
        "#!%s\n"
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, %r)\n"
        "import heavy_resources\n"
        "heavy_resources.account_home = lambda: Path(%r)\n"
        "import heavy_runner\n"
        "raise SystemExit(heavy_runner.main())\n"
        % (os.path.realpath(os.sys.executable), str(SANDBOX), str(home)),
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    return str(wrapper)
