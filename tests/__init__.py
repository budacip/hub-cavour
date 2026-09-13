"""Allow standard-library test discovery to import packages from the src layout."""

from pathlib import Path
import sys


SOURCE_ROOT = str(Path(__file__).resolve().parents[1] / "src")
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)
