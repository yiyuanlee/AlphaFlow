"""Option chain selection (IBKR + pure helpers for tests)."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from alphaflow.options.options_config import OptionsChainParams
from alphaflow.options.types import OptionLeg, OptionQuote

if TYPE_CHECKING:
    from ib_async import IB


def parse_expiry(expiry: str) -> date:
    text = expiry.replace('-', '')[:8]
    return datetime.strptime(text, '%Y%m%d').date()


def days_to_expiry(expiry: str, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    return (parse_expiry(expiry) - as_of).days


def filter_expiries_by_dte(expiries: list[str], params: OptionsChainParams, as_of: date | None = None) -> list[str]:
    valid = [e for e in expiries if params.dte_min <= days_to_expiry(e, as_of) <= params.dte_max]
    return sorted(valid, key=lambda e: days_to_expiry(e, as_of))


def select_expiry(expiries: list[str], params: OptionsChainParams, as_of: date | None = None) -> str | None:
    valid = filter_expiries_by_dte(expiries, params, as_of)
    return valid[0] if valid else None


def select_strike_by_delta(quotes: list[OptionQuote], target_delta: float, right: str) -> OptionQuote | None:
    """Pick OTM strike closest to target |delta|."""
    side = [q for q in quotes if q.right.upper() == right.upper() and q.mid > 0]
    if not side:
        return None
    if right.upper() == 'C':
        otm = [q for q in side if q.delta > 0]
    else:
        otm = [q for q in side if q.delta < 0]
    pool = otm or side
    return min(pool, key=lambda q: abs(abs(q.delta) - target_delta))


def limit_price_from_mid(mid: float, offset_pct: float, action: str) -> float:
    if mid <= 0:
        return 0.01
    if action.upper() == 'SELL':
        return round(max(mid * (1 - offset_pct), 0.01), 2)
    return round(max(mid * (1 + offset_pct), 0.01), 2)


def spread_limit_credit(short_mid: float, long_mid: float, offset_pct: float) -> float:
    credit = short_mid - long_mid
    return round(max(credit * (1 - offset_pct), 0.01), 2)


def build_vertical_put_spread(
    symbol: str,
    expiry: str,
    short_strike: float,
    long_strike: float,
    short_con_id: int = 0,
    long_con_id: int = 0,
) -> list[OptionLeg]:
    return [
        OptionLeg(symbol, expiry, short_strike, 'P', 'SELL', 1, short_con_id),
        OptionLeg(symbol, expiry, long_strike, 'P', 'BUY', 1, long_con_id),
    ]


def build_vertical_call_spread(
    symbol: str,
    expiry: str,
    short_strike: float,
    long_strike: float,
    short_con_id: int = 0,
    long_con_id: int = 0,
) -> list[OptionLeg]:
    return [
        OptionLeg(symbol, expiry, short_strike, 'C', 'SELL', 1, short_con_id),
        OptionLeg(symbol, expiry, long_strike, 'C', 'BUY', 1, long_con_id),
    ]


def _option_mid(ticker: Any) -> tuple[float, float, float, float]:
    bid = float(ticker.bid or 0)
    ask = float(ticker.ask or 0)
    last = float(ticker.last or 0)
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
    model = getattr(ticker, 'modelGreeks', None)
    delta = float(model.delta) if model and model.delta is not None else 0.0
    return bid, ask, mid, delta


def fetch_option_quotes(ib: IB, symbol: str, expiry: str, right: str, strikes: list[float]) -> list[OptionQuote]:
    from ib_async import Option

    quotes: list[OptionQuote] = []
    for strike in strikes:
        contract = Option(symbol, expiry, strike, right, 'SMART', tradingClass=symbol)
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            continue
        contract = qualified[0]
        ticker = ib.reqMktData(contract, genericTickList='106', snapshot=True)
        ib.sleep(0.3)
        bid, ask, mid, delta = _option_mid(ticker)
        ib.cancelMktData(contract)
        if mid <= 0:
            continue
        quotes.append(OptionQuote(
            symbol=symbol,
            expiry=expiry,
            strike=float(strike),
            right=right,
            delta=delta,
            mid=mid,
            bid=bid,
            ask=ask,
            con_id=contract.conId,
        ))
    return quotes


def fetch_chain_expiries(ib: IB, symbol: str) -> list[str]:
    from ib_async import Stock

    stock = Stock(symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)
    params = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
    if not params:
        return []
    expiries: set[str] = set()
    for p in params:
        expiries.update(p.expirations)
    return sorted(expiries)


def fetch_strikes(ib: IB, symbol: str, expiry: str, right: str) -> list[float]:
    from ib_async import Stock

    stock = Stock(symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)
    params = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
    strikes: set[float] = set()
    for p in params:
        if expiry in p.expirations:
            strikes.update(float(s) for s in p.strikes)
    return sorted(strikes)


def pick_otm_option(
    ib: IB,
    symbol: str,
    right: str,
    chain_params: OptionsChainParams,
    delta_target: float,
    as_of: date | None = None,
) -> OptionQuote | None:
    expiries = fetch_chain_expiries(ib, symbol)
    expiry = select_expiry(expiries, chain_params, as_of)
    if not expiry:
        return None
    strikes = fetch_strikes(ib, symbol, expiry, right)
    if not strikes:
        return None
    quotes = fetch_option_quotes(ib, symbol, expiry, right, strikes)
    return select_strike_by_delta(quotes, delta_target, right)
