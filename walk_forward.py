"""
AlphaFlow - Walk-Forward 样本外验证
====================================
训练集优化 → 验证集选参 → 测试集一次性评估（避免过拟合）

用法:
  python walk_forward.py              # 默认 holdout 模式
  python walk_forward.py --rolling    # 滚动 walk-forward
  python walk_forward.py --quick      # 使用较小参数网格（更快）

流程 (holdout):
  1. 在训练集 (2010-2020) 上网格搜索
  2. 取 Top-K 候选在验证集 (2021-2023) 上评估，选出最优
  3. 用选定参数在测试集 (2024-2026) 上做最终样本外评估
"""

import argparse
import sys
import io

from alphaflow.config import load_config
from alphaflow.walkforward import (
    print_walk_forward_summary,
    run_walk_forward,
    save_walk_forward_results,
)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='AlphaFlow Walk-Forward Validation')
    parser.add_argument('--rolling', action='store_true', help='Use rolling walk-forward windows')
    parser.add_argument('--quick', action='store_true', help='Use smaller parameter grid for faster runs')
    parser.add_argument('--portfolio', action='store_true', help='Portfolio-scope holdout (shared capital pool)')
    parser.add_argument('--output', default='walkforward_results.yaml', help='Output YAML path')
    args = parser.parse_args()

    config = load_config()
    wf_cfg = config.setdefault('walk_forward', {})
    if args.rolling:
        wf_cfg['mode'] = 'rolling'
    if args.quick:
        wf_cfg['quick_grid'] = True
    if args.portfolio:
        wf_cfg['scope'] = 'portfolio'

    results = run_walk_forward(config)
    print_walk_forward_summary(results)
    save_walk_forward_results(results, args.output)
    print('\n✅ Walk-Forward 验证完成！')


if __name__ == '__main__':
    main()
