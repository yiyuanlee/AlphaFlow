"""
AlphaFlow - V9 已迁移至期权主策略
用法: python scripts/live/ibkr_trading_system_v9.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup_path

setup_path(__file__)

from ibkr_options import main

if __name__ == '__main__':
    main()
