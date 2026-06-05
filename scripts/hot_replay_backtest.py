"""
AlphaFlow - 热门股扫描器历史回放（日线代理）
============================================
用「每日涨幅榜」代理 IBKR TOP_PERC_GAIN，在固定流动股池上回放入场规则。

用法: python scripts/hot_replay_backtest.py
"""

import sys
import io
import json

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.config import load_config, output_path
from alphaflow.hot_config import hot_config_from_yaml
from alphaflow.hot_replay import run_daily_replay, summarize_replay
from alphaflow.hot_stats import format_replay_stats

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    config = load_config()
    hot = hot_config_from_yaml(config)
    print('\n运行热门股日线回放（扫描器代理）...')
    print(f"  区间: {hot.replay.start_date} ~ {hot.replay.end_date}")
    print(f"  初始资金(个股池): ${hot.replay.initial_cash:,.0f}")

    result = run_daily_replay(config, hot)
    summary = summarize_replay(result)
    print(format_replay_stats(summary))

    out = output_path('hot_replay_results.json')
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\n💾 结果已保存: {out}')


if __name__ == '__main__':
    main()
