"""Compatibility entry point for current Chief/Marginal UI acceptance.

The former Paraxial UI was replaced. Keep this command usable by delegating
to the current acceptance runner rather than keeping obsolete selectors.
Previous run evidence remains under artifacts/ray-smoke/.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.smoke_chief import main


if __name__ == "__main__":
    raise SystemExit(main())
