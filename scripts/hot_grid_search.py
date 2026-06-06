"""
AlphaFlow - 热门股参数敏感性网格
================================
在日线扫描器回放上搜索 min_adx / min_rel_volume / rsi_max / require_golden_cross 等组合。

用法:
  python scripts/hot_grid_search.py
  python scripts/hot_grid_search.py --quick
  python scripts/hot_grid_search.py --objective return --top 20
"""

from __future__ import annotations

import argparse
import sys
import io

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.config import load_config, output_path
from alphaflow.hot_config import hot_config_from_yaml
from alphaflow.hot_grid import format_hot_grid_table, run_hot_grid_search, save_hot_grid_results

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Hot-stock parameter sensitivity grid')
    parser.add_argument('--quick', action='store_true', help='Smaller parameter grid')
    parser.add_argument('--objective', default='balanced', choices=['balanced', 'return', 'trades', 'profit_factor'])
    parser.add_argument('--top', type=int, default=15, help='Top rows to print/save')
    args = parser.parse_args()

    config = load_config()
    hot = hot_config_from_yaml(config)
    combos = 24 if args.quick else 90

    print('\n热门股参数敏感性网格（日线回放）', flush=True)
    print(f"  区间: {hot.replay.start_date} ~ {hot.replay.end_date}", flush=True)
    print(f"  模式: {'quick' if args.quick else 'full'} (~{combos} 组合)", flush=True)
    print(f"  目标: {args.objective}", flush=True)
    print('  首次运行会下载行情（仅一次），请稍候...\n', flush=True)

    def progress(i: int, total: int):
        if i == 1 or i == total or i % max(1, total // 10) == 0:
            print(f'  进度: {i}/{total}', flush=True)

    results = run_hot_grid_search(
        config,
        quick=args.quick,
        objective=args.objective,
        top_k=args.top,
        on_progress=progress,
    )

    print(format_hot_grid_table(results, limit=args.top))

    out_yaml = output_path('hot_grid_results.yaml')
    save_hot_grid_results(results, str(out_yaml))
    print(f'\n💾 Top-{args.top} 已保存: {out_yaml}')


if __name__ == '__main__':
    main()
