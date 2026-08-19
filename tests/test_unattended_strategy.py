from datetime import date, datetime, timedelta, timezone

from alphaflow.options.unattended.config import CoveredCallConfig, SafeExecutionConfig
from alphaflow.options.unattended.strategy import (
    completed_bar_diagnostics,
    exit_reason,
    make_intent,
    next_limit_price,
    select_covered_call_quote,
)
from alphaflow.options.unattended.types import DailyBar, OptionMarketQuote

NOW = datetime(2026, 8, 19, 14, 15, tzinfo=timezone.utc)


def _quote(**overrides) -> OptionMarketQuote:
    values = {
        "symbol": "QQQ",
        "expiry": "20260918",
        "strike": 610.0,
        "right": "C",
        "delta": 0.25,
        "bid": 2.90,
        "ask": 3.10,
        "timestamp": NOW.isoformat(),
        "con_id": 123,
        "multiplier": 100,
        "delayed": False,
    }
    values.update(overrides)
    return OptionMarketQuote(**values)


def test_contract_selection_rejects_itm_wide_stale_and_delayed_quotes():
    strategy = CoveredCallConfig()
    execution = SafeExecutionConfig()
    stale = (NOW - timedelta(seconds=11)).isoformat()
    quotes = [
        _quote(strike=590.0),
        _quote(strike=615.0, bid=1.0, ask=2.0),
        _quote(strike=620.0, timestamp=stale),
        _quote(strike=625.0, delayed=True),
        _quote(strike=610.0),
    ]
    selected = select_covered_call_quote(
        quotes,
        600.0,
        strategy,
        execution,
        as_of=date(2026, 8, 19),
        now=NOW,
    )
    assert selected is not None
    assert selected.strike == 610.0


def test_intent_is_deterministic_and_broker_reference_is_short():
    first = make_intent(
        purpose="entry",
        action="SELL",
        quote=_quote(),
        quantity=1,
        limit_price=3.0,
        session_date="2026-08-19",
        reason="test",
    )
    second = make_intent(
        purpose="entry",
        action="SELL",
        quote=_quote(),
        quantity=1,
        limit_price=3.0,
        session_date="2026-08-19",
        reason="test",
    )
    assert first.intent_id == second.intent_id
    assert first.order_ref == second.order_ref
    assert first.order_ref.startswith("AFV11-")


def test_exit_rules_use_executable_ask_and_dte():
    assert exit_reason(2.0, 1.0, "20260918", 7, date(2026, 8, 19)) == "profit_take_50pct"
    assert exit_reason(2.0, 1.5, "20260825", 7, date(2026, 8, 19)) == "force_exit_dte"
    assert exit_reason(2.0, 1.5, "20260918", 7, date(2026, 8, 19)) is None


def test_selection_uses_closest_delta_across_valid_expiries():
    selected = select_covered_call_quote(
        [
            _quote(expiry="20260911", delta=0.20, con_id=1),
            _quote(expiry="20260925", delta=0.249, con_id=2),
        ],
        600.0,
        CoveredCallConfig(),
        SafeExecutionConfig(),
        as_of=date(2026, 8, 19),
        now=NOW,
    )
    assert selected is not None
    assert selected.con_id == 2


def test_repricing_never_moves_past_executable_quote():
    assert next_limit_price(2.91, "SELL", 0.01, 2.90) == 2.90
    assert next_limit_price(2.90, "SELL", 0.01, 2.90) == 2.90
    assert next_limit_price(3.09, "BUY", 0.01, 3.10) == 3.10
    assert next_limit_price(3.10, "BUY", 0.01, 3.10) == 3.10


def test_completed_bar_diagnostics_records_rsi_and_adx_without_using_them_as_gates():
    bars = [
        DailyBar(f"2026-07-{i + 1:02d}", 100.0 + i, 101.0 + i, 99.0 + i)
        for i in range(28)
    ]
    diagnostics = completed_bar_diagnostics(bars, 20)
    assert diagnostics["bullish"] is True
    assert diagnostics["rsi14"] is not None
    assert diagnostics["adx14"] is not None
