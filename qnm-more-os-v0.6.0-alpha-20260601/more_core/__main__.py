"""Allow ``python -m more_core`` from the repository root."""

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))

# When run from the repo root the outer more_core/ directory (project dir)
# shadows the real Python package at more_core/more_core/.  Fix sys.path
# and clear the stale namespace so the inner package is loaded instead.
if os.path.isfile(os.path.join(_here, "more_core", "__init__.py")):
    sys.modules.pop("more_core", None)
    sys.path.insert(0, _here)

from more_core.cli import main  # noqa: E402

sys.exit(main())
