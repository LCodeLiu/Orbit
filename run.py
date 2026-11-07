"""源码运行入口：python run.py。"""

from __future__ import annotations

import sys

from orbit.app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
