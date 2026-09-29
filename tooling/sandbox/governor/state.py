"""State-directory resolution for the governor (§4, §5.6, §9).

Tests must never touch ~/.keel/governor: they pass an explicit `directory` or set
KEEL_GOVERNOR_STATE_DIR, which this module honours everywhere state is read or written.
"""
import os
from pathlib import Path

from heavy_resources import account_home


def governor_directory():
    override = os.environ.get('KEEL_GOVERNOR_STATE_DIR')
    path = Path(override) if override else account_home() / '.keel' / 'governor'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path
