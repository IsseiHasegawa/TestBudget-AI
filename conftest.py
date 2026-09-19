import sys
from pathlib import Path

# demo_project のテストは `from app.cart import Cart` の形で書くため、
# リポジトリルートと demo_project の両方を import path に載せる。
ROOT = Path(__file__).resolve().parent
for path in (ROOT, ROOT / "demo_project"):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
