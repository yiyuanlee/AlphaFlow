"""IBKR market scanner for dynamic hot-stock universe."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from ib_async import ScannerSubscription, TagValue

from alphaflow.hot_config import HotScannerParams

if TYPE_CHECKING:
    from ib_async import IB

logger = logging.getLogger(__name__)


class HotStockScanner:
    def __init__(self, ib: IB, params: HotScannerParams, exclude: set[str]):
        self.ib = ib
        self.params = params
        self.exclude = exclude
        self._cache: list[str] = []
        self._last_scan = datetime.min

    def get_universe(self, force: bool = False) -> list[str]:
        elapsed = (datetime.now() - self._last_scan).total_seconds()
        if not force and elapsed < self.params.rescan_minutes * 60 and self._cache:
            return self._cache

        try:
            logger.info('🔍 扫描当日热门美股...')
            sub = ScannerSubscription(
                instrument='STK',
                locationCode=self.params.location_code,
                scanCode=self.params.scan_code,
            )
            tags = [
                TagValue('priceAbove', str(self.params.min_price)),
                TagValue('volumeAbove', str(self.params.min_volume)),
            ]
            rows = self.ib.reqScannerData(sub, scannerSubscriptionFilterOptions=tags)
            symbols = []
            for row in rows:
                sym = row.contractDetails.contract.symbol
                if sym in self.exclude:
                    continue
                symbols.append(sym)
                if len(symbols) >= self.params.max_results:
                    break

            if symbols:
                self._cache = symbols
                self._last_scan = datetime.now()
                logger.info(f'热门标的: {", ".join(symbols)}')
            return self._cache
        except Exception as exc:
            logger.warning(f'扫描器不可用: {exc}')
            return self._cache
