"""Keep the command behind a pipe until the supervisor publishes its lease."""
import os
import sys


def main():
    gate = int(sys.argv[1])
    admitted = os.read(gate, 1) == b'1'
    os.close(gate)
    if not admitted:
        return 75  # Supervisor died before admission; never start an unowned job.
    command = sys.argv[2:]
    try:
        os.execvpe(command[0], command, os.environ)
    except OSError as error:
        print('with-heavy-lock: command could not start: ' + str(error), file=sys.stderr)
        return 127


if __name__ == '__main__':
    raise SystemExit(main())
