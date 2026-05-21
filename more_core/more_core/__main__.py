"""Allow ``python -m more_core`` to launch the CLI."""

import sys

from more_core.cli import main

sys.exit(main())
