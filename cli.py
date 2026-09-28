"""ePersona Studio CLI launcher.

Thin bootstrap so `python cli.py ...` works from a checkout without installing
the package. The implementation lives in studio/cli.py.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from studio.cli import main  # noqa: E402

if __name__ == '__main__':
    # Broken pipe (e.g. `studio caption x.jpg | head`) must not print a
    # traceback on exit.
    try:
        sys.exit(main())
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
