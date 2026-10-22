"""Top-level entry point, for Nuitka and plain `python3 baton_main.py`.

`python3 -m baton` uses `baton/__main__.py`; this file exists so the compiler can
be frozen into a standalone binary without the package-relative import.
"""

import sys

from baton.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
