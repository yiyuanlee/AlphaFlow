"""
AlphaFlow - 热门股纸面交易统计
用法: python scripts/hot_paper_stats.py
"""

import sys
import io

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.hot_stats import analyze_paper_journal, format_paper_stats

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    stats = analyze_paper_journal()
    print(format_paper_stats(stats))


if __name__ == '__main__':
    main()
