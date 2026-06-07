"""Polygon.io historical options chain provider.

Uses only endpoints included in the standard Options plan:
- GET /v3/reference/options/contracts          (contract index, as_of)
- GET /v1/open-close/{optionsTicker}/{date}  (daily option close)
- GET /v2/aggs/ticker/{ticker}/range/1/day/... (fallback OHLC)

Does NOT use Snapshot endpoints (/v3/snapshot/options/...) — not on base plan.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from alphaflow.options.chain_data.black_scholes import delta, estimate_vol_from_price
from alphaflow.options.chain_data.cache import ChainDataCache
from alphaflow.options.chain_data.types import HistoricalOptionQuote
from alphaflow.options.options_config import OptionsChainDataParams


class PolygonChainProvider:
    BASE = 'https://api.polygon.io'

    def __init__(self, params: OptionsChainDataParams):
        self.params = params
        self.api_key = os.environ.get(params.api_key_env, '')
        self.cache = ChainDataCache()
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        wait = self.params.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _get_json(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                f'Polygon API key missing. Set environment variable {self.params.api_key_env}.',
            )
        query = dict(query or {})
        query['apiKey'] = self.api_key
        url = f'{self.BASE}{path}?{urlencode(query)}'
        cache_key = url.replace(self.api_key, '***')
        cached = self.cache.get('polygon', cache_key)
        if cached is not None:
            return cached
        self._throttle()
        req = Request(url, headers={'User-Agent': 'AlphaFlow/1.0'})
        try:
            with urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
        except HTTPError as exc:
            raise RuntimeError(f'Polygon HTTP {exc.code}: {exc.reason}') from exc
        except URLError as exc:
            raise RuntimeError(f'Polygon request failed: {exc.reason}') from exc
        self.cache.set('polygon', cache_key, payload)
        return payload

    def _normalize_option_ticker(self, option_ticker: str) -> str:
        return option_ticker if option_ticker.startswith('O:') else f'O:{option_ticker}'

    def get_underlying_close(self, underlying: str, as_of: str) -> float | None:
        payload = self._get_json(
            f'/v2/aggs/ticker/{underlying}/range/1/day/{as_of}/{as_of}',
            {'adjusted': 'true', 'sort': 'asc', 'limit': 1},
        )
        results = payload.get('results') or []
        if not results:
            return None
        return float(results[0]['c'])

    def get_option_close(self, option_ticker: str, as_of: str) -> float | None:
        ticker = self._normalize_option_ticker(option_ticker)

        # Primary: Daily Ticker Summary (included in Options plan)
        oc = self._get_json(f'/v1/open-close/{ticker}/{as_of}')
        if oc.get('status') == 'OK':
            close = oc.get('close')
            if close is not None and float(close) > 0:
                return float(close)

        # Fallback: Custom aggregate bars
        payload = self._get_json(
            f'/v2/aggs/ticker/{ticker}/range/1/day/{as_of}/{as_of}',
            {'adjusted': 'true', 'sort': 'asc', 'limit': 1},
        )
        results = payload.get('results') or []
        if not results:
            return None
        return float(results[0]['c'])

    def _list_contracts(self, underlying: str, as_of: str, right: str, exp_gte: str, exp_lte: str) -> list[dict[str, Any]]:
        contract_type = 'call' if right.upper() == 'C' else 'put'
        query = {
            'underlying_ticker': underlying,
            'contract_type': contract_type,
            'expiration_date.gte': exp_gte,
            'expiration_date.lte': exp_lte,
            'as_of': as_of,
            'limit': 1000,
            'sort': 'strike_price',
            'order': 'asc',
        }
        items: list[dict[str, Any]] = []
        path = '/v3/reference/options/contracts'
        while path:
            if path.startswith('http'):
                # Pagination next_url — fetch directly
                cache_key = path.replace(self.api_key, '***')
                cached = self.cache.get('polygon', cache_key)
                if cached is not None:
                    payload = cached
                else:
                    self._throttle()
                    req = Request(path, headers={'User-Agent': 'AlphaFlow/1.0'})
                    with urlopen(req, timeout=30) as resp:
                        payload = json.loads(resp.read().decode('utf-8'))
                    self.cache.set('polygon', cache_key, payload)
            else:
                payload = self._get_json(path, query)
                query = {}
            items.extend(payload.get('results') or [])
            next_url = payload.get('next_url')
            path = next_url if next_url else ''
        return items

    def _strike_in_otm_band(self, strike: float, spot: float, right: str) -> bool:
        if right.upper() == 'P':
            return spot * 0.80 <= strike <= spot * 0.99
        return spot * 1.01 <= strike <= spot * 1.20

    def get_chain(self, underlying: str, as_of: str, right: str) -> list[HistoricalOptionQuote]:
        spot = self.get_underlying_close(underlying, as_of)
        if spot is None:
            return []
        as_of_date = date.fromisoformat(as_of)
        exp_gte = (as_of_date + timedelta(days=self.params.dte_min)).isoformat()
        exp_lte = (as_of_date + timedelta(days=self.params.dte_max)).isoformat()
        contracts = self._list_contracts(underlying, as_of, right, exp_gte, exp_lte)

        candidates: list[dict[str, Any]] = []
        for item in contracts:
            strike = float(item.get('strike_price', 0))
            ticker = str(item.get('ticker', ''))
            expiry_raw = item.get('expiration_date')
            if not ticker or strike <= 0 or not expiry_raw:
                continue
            if not self._strike_in_otm_band(strike, spot, right):
                continue
            candidates.append(item)

        quotes: list[HistoricalOptionQuote] = []
        for item in candidates:
            expiry = str(item.get('expiration_date', '')).replace('-', '')
            strike = float(item['strike_price'])
            ticker = str(item['ticker'])
            close = self.get_option_close(ticker, as_of)
            if close is None or close <= 0:
                continue
            dte = (date.fromisoformat(str(item.get('expiration_date'))) - as_of_date).days
            vol = estimate_vol_from_price(spot, strike, dte, right, close)
            greek = delta(spot, strike, dte, right, vol)
            quotes.append(HistoricalOptionQuote(
                underlying=underlying,
                option_ticker=ticker,
                expiry=expiry,
                strike=strike,
                right=right.upper(),
                as_of=as_of,
                close=close,
                delta=greek,
                volume=int(item.get('shares_per_contract', 0) or 0),
            ))
        return quotes
