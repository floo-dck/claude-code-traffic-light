"""Make the host package importable no matter which directory pytest runs in.

Running the CLI directly is fine without this, because Python puts a script's
own directory on sys.path. pytest does not, so tests would fail when invoked
from the repository root.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
