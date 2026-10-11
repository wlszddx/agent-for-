import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.argv = [sys.argv[0], "mcp", *sys.argv[1:]]

from repro.__main__ import main

raise SystemExit(main())
