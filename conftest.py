import sys
from pathlib import Path

# Tests under demo_project import as `from app.cart import Cart`, so both the
# repository root and demo_project have to be on the import path.
ROOT = Path(__file__).resolve().parent
for path in (ROOT, ROOT / "demo_project"):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
