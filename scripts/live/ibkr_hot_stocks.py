"""
AlphaFlow - 热门股短线策略（已停用）
====================================
自 V10 起，热门股模块已归档。请改用期权主策略：

  python scripts/live/ibkr_options.py

归档副本: archive/scripts/live/ibkr_hot_stocks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup_path

setup_path(__file__)


def main():
    print(__doc__)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
