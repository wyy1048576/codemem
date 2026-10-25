"""`python -m codemem ...`: the `codemem` command line, for when the command is not on PATH."""

import sys

from .cli import main

sys.exit(main())
