"""Test host with the same explicit bootstrap used by production entries."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import configure
configure()
suite = unittest.defaultTestLoader.discover(sys.argv[1])
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
