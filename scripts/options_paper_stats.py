"""
AlphaFlow - Options paper trade statistics
用法: python scripts/options_paper_stats.py
"""

import io
import sys

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.options.stats import analyze_options_journal, format_options_stats

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    stats = analyze_options_journal()
    print(format_options_stats(stats))


if __name__ == '__main__':
    main()
