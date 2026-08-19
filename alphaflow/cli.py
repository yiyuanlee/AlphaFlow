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
from datetime import date, datetime, timezone

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


def _scalp_context(args: argparse.Namespace):
    profile = getattr(args, "profile", None)
    if profile != "paper_spy_orb":
        raise ValueError("scalping command requires --profile paper_spy_orb")
    from alphaflow.scalping.alerts import build_scalp_alert_sink
    from alphaflow.scalping.broker import IBKRStockBroker
    from alphaflow.scalping.config import scalp_config_from_yaml
    from alphaflow.scalping.service import ScalpingService
    from alphaflow.scalping.store import ScalpingStore

    raw = load_config(getattr(args, "config", None), profile=profile)
    config = scalp_config_from_yaml(raw)
    store = ScalpingStore(config.persistence.database, config.persistence.journal)
    alerts = build_scalp_alert_sink(config.alerts, store)
    broker = IBKRStockBroker(config.broker)
    service = ScalpingService(config, broker, store, alerts)
    return config, store, alerts, broker, service


def _cmd_scalp_download(args: argparse.Namespace) -> int:
    from alphaflow.scalping.clock import ET, XnysClock
    from alphaflow.scalping.data import MinuteBarCache

    config, _store, _alerts, broker, _service = _scalp_context(args)
    errors = config.validate(require_account=True)
    if errors:
        print(json.dumps({"ok": False, "issues": errors}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    clock = XnysClock()
    default_start, default_end = clock.complete_month_window(datetime.now(timezone.utc).astimezone(ET).date(), months=3)
    start = date.fromisoformat(args.start) if args.start else default_start
    end = date.fromisoformat(args.end) if args.end else default_end
    cache = MinuteBarCache(config.backtest.cache_path)
    try:
        broker.connect()
        account = broker.account_snapshot()
        if account.account_id != config.expected_account_id or not account.account_id.startswith("DU"):
            print("Refusing historical request through the wrong/non-paper account.", file=sys.stderr)
            return 2
        counts = cache.session_counts()
        expected_sessions = [
            label.date()
            for label in clock.calendar.sessions_in_range(start.isoformat(), end.isoformat()).to_pydatetime()
        ]
        incomplete: list[date] = []
        for session_date in expected_sessions:
            schedule = clock.schedule(session_date)
            expected_count = int((schedule.close_utc - schedule.open_utc).total_seconds() // 60) if schedule else 0
            if counts.get(session_date, 0) < expected_count:
                incomplete.append(session_date)
        downloaded = (
            broker.historical_minutes(
                config.strategy.symbol,
                min(incomplete) if incomplete else start,
                max(incomplete) if incomplete else start,
            )
            if incomplete
            else []
        )
        added = cache.merge(downloaded) if downloaded else 0
        final_counts = cache.session_counts()
        still_incomplete: list[str] = []
        for session_date in expected_sessions:
            schedule = clock.schedule(session_date)
            expected_count = int((schedule.close_utc - schedule.open_utc).total_seconds() // 60) if schedule else 0
            if final_counts.get(session_date, 0) < expected_count:
                still_incomplete.append(session_date.isoformat())
        result = {
            "ok": not still_incomplete,
            "path": str(cache.path),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "downloaded_bars": len(downloaded),
            "new_bars": added,
            "sessions": len(expected_sessions),
            "missing_sessions": still_incomplete,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    finally:
        broker.disconnect()


def _cmd_scalp_backtest(args: argparse.Namespace) -> int:
    from alphaflow.scalping.backtest import validate_three_month_backtest
    from alphaflow.scalping.clock import ET, XnysClock
    from alphaflow.scalping.data import MinuteBarCache

    config, store, _alerts, _broker, _service = _scalp_context(args)
    errors = config.validate(require_account=False)
    if errors:
        print(json.dumps({"ok": False, "issues": errors}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    clock = XnysClock()
    default_start, default_end = clock.complete_month_window(datetime.now(timezone.utc).astimezone(ET).date(), months=3)
    start = date.fromisoformat(args.start) if args.start else default_start
    end = date.fromisoformat(args.end) if args.end else default_end
    cache = MinuteBarCache(config.backtest.cache_path)
    counts = cache.session_counts()
    incomplete: list[str] = []
    for label in clock.calendar.sessions_in_range(start.isoformat(), end.isoformat()).to_pydatetime():
        session_date = label.date()
        schedule = clock.schedule(session_date)
        expected_count = int((schedule.close_utc - schedule.open_utc).total_seconds() // 60) if schedule else 0
        if counts.get(session_date, 0) < expected_count:
            incomplete.append(session_date.isoformat())
    if incomplete:
        store.set_metadata("backtest_passed", "false")
        print(
            json.dumps(
                {
                    "passed": False,
                    "error": "minute cache has incomplete XNYS sessions",
                    "sessions": incomplete,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    bars = cache.to_frame(start, end)
    results = validate_three_month_backtest(bars, config)
    payload = {
        "passed": results["passed"],
        "paper_gate_eligible": results["passed"] and start == default_start and end == default_end,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "full": results["full"].to_dict(),
        "out_of_sample": results["out_of_sample"].to_dict(),
    }
    gate_passed = bool(payload["paper_gate_eligible"])
    store.set_metadata("backtest_passed", "true" if gate_passed else "false")
    store.set_metadata("backtest_window", f"{start.isoformat()}:{end.isoformat()}")
    store.set_metadata(
        "backtest_summary",
        json.dumps(
            {
                "full_trades": len(results["full"].trades),
                "full_pf": results["full"].profit_factor,
                "oos_trades": len(results["out_of_sample"].trades),
                "oos_pf": results["out_of_sample"].profit_factor,
            }
        ),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if results["passed"] else 1


def _cmd_scalp_doctor(args: argparse.Namespace) -> int:
    _config, _store, _alerts, broker, service = _scalp_context(args)
    try:
        result = service.doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["ok"] else 1
    finally:
        broker.disconnect()


def _cmd_scalp_run(args: argparse.Namespace) -> int:
    _config, _store, _alerts, broker, service = _scalp_context(args)
    try:
        if args.daemon:
            service.run_daemon()
            return 0
        result = service.run_cycle()
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
        return 0 if not result.halted else 1
    finally:
        broker.disconnect()


def _cmd_scalp_status(args: argparse.Namespace) -> int:
    config, store, _alerts, _broker, _service = _scalp_context(args)
    result = store.status_dict(config.persistence.halt_file)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 1 if result["halted"] else 0


def _cmd_scalp_reconcile(args: argparse.Namespace) -> int:
    _config, _store, _alerts, broker, service = _scalp_context(args)
    try:
        result = service.reconcile()
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
        return 0 if result.ok else 1
    finally:
        broker.disconnect()


def _cmd_scalp_halt(args: argparse.Namespace) -> int:
    _config, _store, _alerts, broker, service = _scalp_context(args)
    try:
        service.manual_halt(args.reason)
        print(f"SCALPER HALTED: {args.reason}")
        return 0
    finally:
        broker.disconnect()


def _cmd_scalp_resume(args: argparse.Namespace) -> int:
    _config, _store, _alerts, broker, service = _scalp_context(args)
    try:
        result = service.manual_resume(args.confirm_account)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
        return 0 if result.ok else 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        broker.disconnect()


def _cmd_scalp_watchdog(args: argparse.Namespace) -> int:
    from alphaflow.scalping.watchdog import check_scalp_heartbeat

    config, store, alerts, _broker, _service = _scalp_context(args)
    ok, message = check_scalp_heartbeat(config, store, alerts)
    print(message)
    return 0 if ok else 1


def _cmd_legacy_equity_run(_args: argparse.Namespace) -> int:
    print(
        "[!] V8 指数动量已降级；主实盘入口为 ``alphaflow options run``。\n    继续运行可能与期权底仓冲突。",
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

    run = options_sub.add_parser("run", help="Run V11 profile or safe legacy dry-run", parents=[global_parser])
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Single cycle (default)")
    mode.add_argument("--live", action="store_true", help="Legacy single cycle (always forced to dry-run)")
    mode.add_argument("--loop", action="store_true", help="Legacy loop (always forced to dry-run)")
    mode.add_argument("--daemon", action="store_true", help="Run the V11 profile continuously")
    run.add_argument("--dry-run", action="store_true", help="Connect but do not place orders")
    run.set_defaults(handler=_cmd_options_run)

    doctor = options_sub.add_parser("doctor", help="Read-only V11 Gateway/account/data checks", parents=[global_parser])
    doctor.set_defaults(handler=_cmd_options_doctor)

    status = options_sub.add_parser(
        "status", help="Show persisted V11 health and trading state", parents=[global_parser]
    )
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    status.set_defaults(handler=_cmd_options_status)

    reconcile = options_sub.add_parser("reconcile", help="Reconcile V11 state with IBKR", parents=[global_parser])
    reconcile.add_argument(
        "--accept-legacy",
        action="store_true",
        help="Accept an imported legacy position only when it exactly matches IBKR",
    )
    reconcile.set_defaults(handler=_cmd_options_reconcile)

    halt = options_sub.add_parser("halt", help="Block new entries while preserving risk exits", parents=[global_parser])
    halt.add_argument("--reason", required=True)
    halt.set_defaults(handler=_cmd_options_halt)

    resume = options_sub.add_parser(
        "resume", help="Clear HALT after a successful reconciliation", parents=[global_parser]
    )
    resume.add_argument("--confirm-account", required=True)
    resume.set_defaults(handler=_cmd_options_resume)

    watchdog = options_sub.add_parser("watchdog", help="Check the V11 daemon heartbeat", parents=[global_parser])
    watchdog.set_defaults(handler=_cmd_options_watchdog)

    stats = options_sub.add_parser("stats", help="Paper trade statistics")
    stats.set_defaults(handler=_cmd_options_stats)

    replay = options_sub.add_parser("replay-proxy", help="Route replay proxy backtest")
    replay.set_defaults(handler=_cmd_options_replay_proxy)

    # --- isolated SPY opening-range scalper ---
    scalp = sub.add_parser(
        "scalp",
        help="Independent SPY opening-range shadow/paper runtime",
        parents=[global_parser],
    )
    scalp_sub = scalp.add_subparsers(dest="scalp_cmd", required=True)

    scalp_download = scalp_sub.add_parser(
        "download", help="Download resumable IBKR RTH 1-minute bars", parents=[global_parser]
    )
    scalp_download.add_argument("--start", help="First session date (YYYY-MM-DD)")
    scalp_download.add_argument("--end", help="Last session date (YYYY-MM-DD)")
    scalp_download.set_defaults(handler=_cmd_scalp_download)

    scalp_backtest = scalp_sub.add_parser(
        "backtest", help="Run the three-month causal ORB validation", parents=[global_parser]
    )
    scalp_backtest.add_argument("--start", help="First session date (YYYY-MM-DD)")
    scalp_backtest.add_argument("--end", help="Last session date (YYYY-MM-DD)")
    scalp_backtest.set_defaults(handler=_cmd_scalp_backtest)

    scalp_doctor = scalp_sub.add_parser(
        "doctor", help="Read-only account/Gateway/data/shorting checks", parents=[global_parser]
    )
    scalp_doctor.set_defaults(handler=_cmd_scalp_doctor)

    scalp_run = scalp_sub.add_parser("run", help="Run one scalping cycle or the daemon", parents=[global_parser])
    scalp_run.add_argument("--daemon", action="store_true")
    scalp_run.set_defaults(handler=_cmd_scalp_run)

    scalp_status = scalp_sub.add_parser("status", help="Show persisted scalper health", parents=[global_parser])
    scalp_status.add_argument("--json", action="store_true")
    scalp_status.set_defaults(handler=_cmd_scalp_status)

    scalp_reconcile = scalp_sub.add_parser(
        "reconcile", help="Rebuild the local view from exact IBKR orderRefs", parents=[global_parser]
    )
    scalp_reconcile.set_defaults(handler=_cmd_scalp_reconcile)

    scalp_halt = scalp_sub.add_parser(
        "halt", help="Block entries and cancel known pending entries", parents=[global_parser]
    )
    scalp_halt.add_argument("--reason", required=True)
    scalp_halt.set_defaults(handler=_cmd_scalp_halt)

    scalp_resume = scalp_sub.add_parser(
        "resume", help="Clear HALT after exact-account reconciliation", parents=[global_parser]
    )
    scalp_resume.add_argument("--confirm-account", required=True)
    scalp_resume.set_defaults(handler=_cmd_scalp_resume)

    scalp_watchdog = scalp_sub.add_parser(
        "watchdog", help="Check the independent scalper heartbeat", parents=[global_parser]
    )
    scalp_watchdog.set_defaults(handler=_cmd_scalp_watchdog)

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
