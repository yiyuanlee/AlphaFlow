"""
AlphaFlow unified CLI.

Thin entry point that delegates to library functions or legacy scripts during
the directory migration. Existing ``python scripts/...`` invocations remain
supported.

Examples
--------
    alphaflow backtest run
    alphaflow research walk-forward --quick
    alphaflow research verify-indicators
    alphaflow options scan
    alphaflow options run --live --dry-run
    alphaflow options stats
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from alphaflow.config import PROJECT_ROOT, load_config, output_path

__all__ = ["main", "build_parser"]


def _configure_stdio() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def _run_legacy_script(relative_path: str, argv: Sequence[str] | None = None) -> int:
    """Run an existing script under ``scripts/`` (migration bridge)."""
    script = PROJECT_ROOT / relative_path
    if not script.is_file():
        print(f"[!] Script not found: {script}", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(script), *(argv or [])]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return int(result.returncode)


def _cmd_backtest_run(_args: argparse.Namespace) -> int:
    return _run_legacy_script("scripts/backtest_main.py")


def _cmd_research_walk_forward(args: argparse.Namespace) -> int:
    from alphaflow.research.walkforward import (
        print_walk_forward_summary,
        run_walk_forward,
        save_walk_forward_results,
    )

    config = load_config(args.config)
    wf_cfg = config.setdefault("walk_forward", {})
    if args.rolling:
        wf_cfg["mode"] = "rolling"
    if args.quick:
        wf_cfg["quick_grid"] = True
    if args.portfolio:
        wf_cfg["scope"] = "portfolio"

    results = run_walk_forward(config)
    print_walk_forward_summary(results)
    save_walk_forward_results(results, args.output)
    print("\n✅ Walk-Forward 验证完成！")
    return 0


def _cmd_research_optimize(_args: argparse.Namespace) -> int:
    return _run_legacy_script("scripts/optimize.py")


def _cmd_research_verify(args: argparse.Namespace) -> int:
    from alphaflow.research.parity import run_parity_check

    config = load_config(args.config)
    tickers = args.ticker or ["QQQ", "VOO"]
    all_passed = True

    for ticker in tickers:
        result = run_parity_check(ticker, config)
        if result is None:
            print(f"  [!] {ticker}: 数据不足，跳过")
            all_passed = False
            continue
        status = "PASS" if result.passed else "FAIL"
        print(f"\n{ticker}: {status}  ({result.pass_rate:.2f}% over {result.rows_compared} rows)")
        if not result.passed:
            all_passed = False
            for failure in result.failures[:5]:
                print(f"  - {failure['date']}: {failure['issues']}")

    return 0 if all_passed else 1


def _cmd_options_scan(args: argparse.Namespace) -> int:
    from alphaflow.options.daily_scan import format_daily_scan, run_daily_scan

    report = run_daily_scan(as_of=args.date, use_chain=not args.no_chain)
    print(format_daily_scan(report))
    return 0


def _cmd_options_run(args: argparse.Namespace) -> int:
    argv: list[str] = []
    if args.loop:
        argv.append("--loop")
    elif args.live:
        argv.append("--live")
    else:
        argv.append("--once")
    if args.dry_run:
        argv.append("--dry-run")
    return _run_legacy_script("scripts/live/ibkr_options.py", argv)


def _cmd_options_stats(_args: argparse.Namespace) -> int:
    from alphaflow.options.stats import analyze_options_journal, format_options_stats

    stats = analyze_options_journal()
    print(format_options_stats(stats))
    return 0


def _cmd_options_replay_proxy(_args: argparse.Namespace) -> int:
    return _run_legacy_script("scripts/options_replay_proxy.py")


def _cmd_legacy_equity_run(_args: argparse.Namespace) -> int:
    print(
        "[!] V8 指数动量已降级；主实盘入口为 ``alphaflow options run``。\n"
        "    继续运行可能与期权底仓冲突。",
        file=sys.stderr,
    )
    return _run_legacy_script("scripts/live/ibkr_trading_system_v8.py")


def _cmd_legacy_hot_stats(_args: argparse.Namespace) -> int:
    return _run_legacy_script("scripts/hot_paper_stats.py")


def build_parser() -> argparse.ArgumentParser:
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument(
        "--config",
        default=None,
        help="Path to config YAML (default: ./config.yaml)",
    )

    parser = argparse.ArgumentParser(
        prog="alphaflow",
        description="AlphaFlow — IBKR quantitative trading CLI",
        parents=[global_parser],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- backtest ---
    backtest = sub.add_parser(
        "backtest",
        help="Historical backtests",
        parents=[global_parser],
    )
    backtest_sub = backtest.add_subparsers(dest="backtest_cmd", required=True)
    backtest_run = backtest_sub.add_parser("run", help="Portfolio + single-ticker backtest")
    backtest_run.set_defaults(handler=_cmd_backtest_run)

    # --- research ---
    research = sub.add_parser(
        "research",
        help="Optimization and validation",
        parents=[global_parser],
    )
    research_sub = research.add_subparsers(dest="research_cmd", required=True)

    wf = research_sub.add_parser("walk-forward", help="Walk-forward out-of-sample validation")
    wf.add_argument("--rolling", action="store_true")
    wf.add_argument("--quick", action="store_true")
    wf.add_argument("--portfolio", action="store_true")
    wf.add_argument(
        "--output",
        default=str(output_path("walkforward_results.yaml")),
        help="Output YAML path",
    )
    wf.set_defaults(handler=_cmd_research_walk_forward)

    opt = research_sub.add_parser("optimize", help="Parameter grid search")
    opt.set_defaults(handler=_cmd_research_optimize)

    verify = research_sub.add_parser("verify-indicators", help="Backtrader vs live indicator parity")
    verify.add_argument("--ticker", action="append", dest="ticker")
    verify.set_defaults(handler=_cmd_research_verify)

    # --- options (primary live path) ---
    options = sub.add_parser(
        "options",
        help="Options strategy (V10 primary)",
        parents=[global_parser],
    )
    options_sub = options.add_subparsers(dest="options_cmd", required=True)

    scan = options_sub.add_parser("scan", help="Daily offline scan (~10s, no IBKR)")
    scan.add_argument("--no-chain", action="store_true")
    scan.add_argument("--date", default=None)
    scan.set_defaults(handler=_cmd_options_scan)

    run = options_sub.add_parser("run", help="Connect IBKR and execute one cycle")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Single cycle (default)")
    mode.add_argument("--live", action="store_true", help="Single live cycle")
    mode.add_argument("--loop", action="store_true", help="Long-running loop (requires TWS)")
    run.add_argument("--dry-run", action="store_true", help="Connect but do not place orders")
    run.set_defaults(handler=_cmd_options_run)

    stats = options_sub.add_parser("stats", help="Paper trade statistics")
    stats.set_defaults(handler=_cmd_options_stats)

    replay = options_sub.add_parser("replay-proxy", help="Route replay proxy backtest")
    replay.set_defaults(handler=_cmd_options_replay_proxy)

    # --- legacy / archived ---
    legacy = sub.add_parser(
        "legacy",
        help="Deprecated strategies (archived)",
        parents=[global_parser],
    )
    legacy_sub = legacy.add_subparsers(dest="legacy_cmd", required=True)

    equity = legacy_sub.add_parser("equity-run", help="V8 index trend (deprecated)")
    equity.set_defaults(handler=_cmd_legacy_equity_run)

    hot = legacy_sub.add_parser("hot-stats", help="V9 hot-stock paper stats (archived)")
    hot.set_defaults(handler=_cmd_legacy_hot_stats)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
