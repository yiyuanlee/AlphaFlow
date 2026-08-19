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
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict

from alphaflow.config import PROJECT_ROOT, load_config, output_path

__all__ = ["build_parser", "main"]


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
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
    return int(result.returncode)


def _cmd_backtest_run(_args: argparse.Namespace) -> int:
    return _run_legacy_script("scripts/backtest_main.py")


def _cmd_research_walk_forward(args: argparse.Namespace) -> int:
    from alphaflow.research.walkforward import (
        print_walk_forward_summary,
        run_walk_forward,
        save_walk_forward_results,
    )

    config = load_config(getattr(args, "config", None))
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

    config = load_config(getattr(args, "config", None))
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


def _v11_context(args: argparse.Namespace):
    profile = getattr(args, "profile", None)
    if profile != "paper_qqq_cc":
        raise ValueError("V11 command requires --profile paper_qqq_cc")
    from alphaflow.options.unattended.alerts import build_alert_sink
    from alphaflow.options.unattended.broker import IBKRBroker
    from alphaflow.options.unattended.config import unattended_config_from_yaml
    from alphaflow.options.unattended.service import UnattendedService
    from alphaflow.options.unattended.store import UnattendedStore

    config = load_config(getattr(args, "config", None), profile=profile)
    unattended = unattended_config_from_yaml(config)
    store = UnattendedStore(unattended.persistence.database)
    store.import_legacy_positions(PROJECT_ROOT / "state" / "options_positions.json")
    alerts = build_alert_sink(unattended.alerts, store, unattended.persistence.journal)
    broker = IBKRBroker(unattended.broker)
    service = UnattendedService(unattended, broker, store, alerts)
    return unattended, store, alerts, broker, service


def _cmd_options_run(args: argparse.Namespace) -> int:
    if getattr(args, "profile", None):
        _config, store, _alerts, broker, service = _v11_context(args)
        try:
            if args.daemon:
                service.run_daemon()
            else:
                result = service.run_cycle()
                print(json.dumps(asdict(result) if result else store.status_dict(), ensure_ascii=False, indent=2))
                return 0 if result and result.ok else 1
        finally:
            broker.disconnect()
        return 0

    argv: list[str] = []
    if args.loop:
        argv.append("--loop")
    elif args.live:
        argv.append("--live")
    else:
        argv.append("--once")
    # V10 is permanently fail-safe from the unified CLI. V11 is the only
    # profile allowed to submit paper orders.
    argv.append("--dry-run")
    if not args.dry_run:
        print("[!] Legacy V10 forced to dry-run; use --profile paper_qqq_cc for V11.", file=sys.stderr)
    return _run_legacy_script("scripts/live/ibkr_options.py", argv)


def _cmd_options_doctor(args: argparse.Namespace) -> int:
    _config, _store, _alerts, broker, service = _v11_context(args)
    try:
        result = service.doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    finally:
        broker.disconnect()


def _cmd_options_status(args: argparse.Namespace) -> int:
    config, store, _alerts, _broker, _service = _v11_context(args)
    result = store.status_dict(config.persistence.halt_file)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 1 if result["halted"] else 0


def _cmd_options_reconcile(args: argparse.Namespace) -> int:
    _config, _store, _alerts, broker, service = _v11_context(args)
    try:
        result = service.reconcile(accept_legacy=args.accept_legacy)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1
    finally:
        broker.disconnect()


def _cmd_options_halt(args: argparse.Namespace) -> int:
    config, store, alerts, _broker, _service = _v11_context(args)
    store.set_halt(args.reason, config.persistence.halt_file)
    alerts.send("manual_halt", f"Manual HALT: {args.reason}", critical=True)
    print(f"HALTED: {args.reason}")
    return 0


def _cmd_options_resume(args: argparse.Namespace) -> int:
    config, store, alerts, broker, service = _v11_context(args)
    expected = config.expected_account_id
    if not expected or args.confirm_account != expected:
        print("Account confirmation does not match IBKR_PAPER_ACCOUNT.", file=sys.stderr)
        return 2
    try:
        result = service.reconcile(halt_on_error=False)
        if not result.ok:
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        store.clear_halt(config.persistence.halt_file)
        alerts.send("manual_resume", f"Trading resumed for paper account {expected}")
        print(f"RESUMED: {expected}")
        return 0
    finally:
        broker.disconnect()


def _cmd_options_watchdog(args: argparse.Namespace) -> int:
    from alphaflow.options.unattended.watchdog import check_heartbeat

    config, store, alerts, _broker, _service = _v11_context(args)
    ok, message = check_heartbeat(config, store, alerts)
    print(message)
    return 0 if ok else 1


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
        default=argparse.SUPPRESS,
        help="Path to config YAML (default: ./config.yaml)",
    )
    global_parser.add_argument(
        "--profile",
        default=argparse.SUPPRESS,
        help="Merged config profile name, for example paper_qqq_cc",
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
        help="Options strategies and V11 unattended paper runtime",
        parents=[global_parser],
    )
    options_sub = options.add_subparsers(dest="options_cmd", required=True)

    scan = options_sub.add_parser("scan", help="Daily offline scan (~10s, no IBKR)")
    scan.add_argument("--no-chain", action="store_true")
    scan.add_argument("--date", default=None)
    scan.set_defaults(handler=_cmd_options_scan)

    run = options_sub.add_parser(
        "run", help="Run V11 profile or safe legacy dry-run", parents=[global_parser]
    )
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Single cycle (default)")
    mode.add_argument("--live", action="store_true", help="Legacy single cycle (always forced to dry-run)")
    mode.add_argument("--loop", action="store_true", help="Legacy loop (always forced to dry-run)")
    mode.add_argument("--daemon", action="store_true", help="Run the V11 profile continuously")
    run.add_argument("--dry-run", action="store_true", help="Connect but do not place orders")
    run.set_defaults(handler=_cmd_options_run)

    doctor = options_sub.add_parser(
        "doctor", help="Read-only V11 Gateway/account/data checks", parents=[global_parser]
    )
    doctor.set_defaults(handler=_cmd_options_doctor)

    status = options_sub.add_parser(
        "status", help="Show persisted V11 health and trading state", parents=[global_parser]
    )
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    status.set_defaults(handler=_cmd_options_status)

    reconcile = options_sub.add_parser(
        "reconcile", help="Reconcile V11 state with IBKR", parents=[global_parser]
    )
    reconcile.add_argument(
        "--accept-legacy",
        action="store_true",
        help="Accept an imported legacy position only when it exactly matches IBKR",
    )
    reconcile.set_defaults(handler=_cmd_options_reconcile)

    halt = options_sub.add_parser(
        "halt", help="Block new entries while preserving risk exits", parents=[global_parser]
    )
    halt.add_argument("--reason", required=True)
    halt.set_defaults(handler=_cmd_options_halt)

    resume = options_sub.add_parser(
        "resume", help="Clear HALT after a successful reconciliation", parents=[global_parser]
    )
    resume.add_argument("--confirm-account", required=True)
    resume.set_defaults(handler=_cmd_options_resume)

    watchdog = options_sub.add_parser(
        "watchdog", help="Check the V11 daemon heartbeat", parents=[global_parser]
    )
    watchdog.set_defaults(handler=_cmd_options_watchdog)

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
