"""
conftest.py — Project-root pytest configuration
================================================
Adds the workspace root to sys.path so that `from backend.xxx import yyy`
resolves correctly regardless of which directory pytest is invoked from
(e.g. `pytest` from project root, `pytest tests/` from root, or
`cd tests && pytest` inside the tests folder).
"""
import sys
from pathlib import Path

# Always ensure the project root is first on sys.path
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
