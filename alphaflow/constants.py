"""Shared constants used across backtest, optimize, and live trading."""

INDEX_TICKERS = frozenset({'VOO', 'QQQ'})


def is_index(symbol: str) -> bool:
    return symbol in INDEX_TICKERS
