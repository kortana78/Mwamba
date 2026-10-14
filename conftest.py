import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
GEO = os.path.join(ROOT, "packages", "geo")
if GEO not in sys.path:
    sys.path.insert(0, GEO)
