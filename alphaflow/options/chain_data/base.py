"""Chain data provider factory."""

from __future__ import annotations

from typing import Protocol

from alphaflow.options.chain_data.types import HistoricalOptionQuote
from alphaflow.options.options_config import OptionsChainDataParams


class ChainDataProvider(Protocol):
    def get_chain(self, underlying: str, as_of: str, right: str) -> list[HistoricalOptionQuote]:
        ...

    def get_option_close(self, option_ticker: str, as_of: str) -> float | None:
        ...

    def get_underlying_close(self, underlying: str, as_of: str) -> float | None:
        ...


def create_chain_provider(params: OptionsChainDataParams) -> ChainDataProvider:
    provider = params.provider.lower()
    if provider == 'polygon':
        from alphaflow.options.chain_data.polygon import PolygonChainProvider

        return PolygonChainProvider(params)
    if provider == 'csv':
        from alphaflow.options.chain_data.csv_provider import CsvChainProvider

        return CsvChainProvider(params)
    if provider == 'yfinance':
        from alphaflow.options.chain_data.yfinance_provider import YFinanceChainProvider

        return YFinanceChainProvider(params)
    raise ValueError(f'Unknown chain data provider: {provider}')
