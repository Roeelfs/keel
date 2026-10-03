"""Block until the steward inbox grows, then print the new lines and exit.

The machine-steward's only wake (founder ruling 2026-10-01: no timers). Uses kqueue, so it costs
no CPU while waiting and needs no polling interval. Run backgrounded; its exit re-invokes the session.
"""
import os
from pathlib import Path
import select
import sys

INBOX = Path(os.path.expanduser('~/.keel/governor/steward-inbox.jsonl'))


def wait(path=INBOX):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    start = path.stat().st_size
    fd = os.open(path, os.O_RDONLY)
    try:
        kq = select.kqueue()
        ev = select.kevent(fd, filter=select.KQ_FILTER_VNODE, flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                           fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME)
        while path.stat().st_size <= start:
            kq.control([ev], 1, None)
            if not path.exists() or os.fstat(fd).st_ino != path.stat().st_ino:
                return ''
        with path.open() as inbox:
            inbox.seek(start)
            return inbox.read()
    finally:
        os.close(fd)


if __name__ == '__main__':
    sys.stdout.write(wait(Path(sys.argv[1]) if len(sys.argv) > 1 else INBOX))
