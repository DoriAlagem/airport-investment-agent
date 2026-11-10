"""Puts src/ on the path for every test module, so none has to do it itself."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
