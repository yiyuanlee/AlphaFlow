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

from alphaflow.options.chain_data.black_scholes import (
    delta,
    estimate_vol_from_price,
    option_price,
    target_strike,
)
from alphaflow.options.chain import filter_expiries_by_dte, select_expiry
from alphaflow.options.chain_data.cache import ChainDataCache
from alphaflow.options.chain_data.types import HistoricalOptionQuote
from alphaflow.options.options_config import OptionsChainDataParams, OptionsChainParams


class PolygonChainProvider:
    BASE = 'https://api.polygon.io'

    def __init__(self, params: OptionsChainDataParams):
        self.params = params
        self.api_key = os.environ.get(params.api_key_env, '')
        self.cache = ChainDataCache()
        self._last_request = 0.0
        self._session_chain_cache: dict[tuple[str, str, str], list[HistoricalOptionQuote]] = {}

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
        for attempt in range(4):
            self._throttle()
            req = Request(url, headers={'User-Agent': 'AlphaFlow/1.0'})
            try:
                with urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode('utf-8'))
                self.cache.set('polygon', cache_key, payload)
                return payload
            except HTTPError as exc:
                if exc.code == 429 and attempt < 3:
                    time.sleep(12 * (attempt + 1))
                    continue
                raise RuntimeError(f'Polygon HTTP {exc.code}: {exc.reason}') from exc
            except URLError as exc:
                raise RuntimeError(f'Polygon request failed: {exc.reason}') from exc
        raise RuntimeError('Polygon request failed after retries')

    def _normalize_option_ticker(self, option_ticker: str) -> str:
        return option_ticker if option_ticker.startswith('O:') else f'O:{option_ticker}'

    def get_underlying_close(self, underlying: str, as_of: str) -> float | None:
        try:
            payload = self._get_json(
                f'/v2/aggs/ticker/{underlying}/range/1/day/{as_of}/{as_of}',
                {'adjusted': 'true', 'sort': 'asc', 'limit': 1},
            )
            results = payload.get('results') or []
            if results:
                return float(results[0]['c'])
        except RuntimeError:
            pass
        return self._underlying_close_yfinance(underlying, as_of)

    def _underlying_close_yfinance(self, underlying: str, as_of: str) -> float | None:
        from alphaflow.data import fetch_data

        start = (date.fromisoformat(as_of) - timedelta(days=7)).isoformat()
        end = (date.fromisoformat(as_of) + timedelta(days=1)).isoformat()
        df = fetch_data(underlying, start, end)
        if df is None or df.empty:
            return None
        day = date.fromisoformat(as_of)
        for idx, row in df.iterrows():
            idx_date = idx.date() if hasattr(idx, 'date') else date.fromisoformat(str(idx)[:10])
            if idx_date == day:
                return float(row['close'])
        return float(df['close'].iloc[-1])

    def get_option_close(self, option_ticker: str, as_of: str) -> float | None:
        ticker = self._normalize_option_ticker(option_ticker)

        try:
            oc = self._get_json(f'/v1/open-close/{ticker}/{as_of}')
            if oc.get('status') == 'OK':
                close = oc.get('close')
                if close is not None and float(close) > 0:
                    return float(close)
        except RuntimeError:
            pass

        try:
            payload = self._get_json(
                f'/v2/aggs/ticker/{ticker}/range/1/day/{as_of}/{as_of}',
                {'adjusted': 'true', 'sort': 'asc', 'limit': 1},
            )
            results = payload.get('results') or []
            if results:
                return float(results[0]['c'])
        except RuntimeError:
            pass
        return None

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
        pages = 0
        max_pages = 1 if self.params.fast_mode else None
        while path:
            pages += 1
            if max_pages is not None and pages > max_pages:
                break
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
        cache_key = (underlying, as_of, right.upper())
        if cache_key in self._session_chain_cache:
            return self._session_chain_cache[cache_key]
        spot = self.get_underlying_close(underlying, as_of)
        if spot is None:
            return []
        as_of_date = date.fromisoformat(as_of)
        exp_gte = (as_of_date + timedelta(days=self.params.dte_min)).isoformat()
        exp_lte = (as_of_date + timedelta(days=self.params.dte_max)).isoformat()
        contracts = self._list_contracts(underlying, as_of, right, exp_gte, exp_lte)

        chain_params = OptionsChainParams(dte_min=self.params.dte_min, dte_max=self.params.dte_max)
        expiries = filter_expiries_by_dte(
            sorted({str(c.get('expiration_date', '')).replace('-', '') for c in contracts if c.get('expiration_date')}),
            chain_params,
            as_of_date,
        )
        expiry_pick = select_expiry(expiries, chain_params, as_of_date)
        if not expiry_pick:
            return []

        tgt = target_strike(spot, right)
        pool: list[dict[str, Any]] = []
        for item in contracts:
            expiry = str(item.get('expiration_date', '')).replace('-', '')
            if expiry != expiry_pick:
                continue
            strike = float(item.get('strike_price', 0))
            ticker = str(item.get('ticker', ''))
            if not ticker or strike <= 0:
                continue
            if not self._strike_in_otm_band(strike, spot, right):
                continue
            pool.append(item)
        pool.sort(key=lambda c: abs(float(c['strike_price']) - tgt))
        pool = pool[: self.params.max_strikes_per_expiry]

        quotes: list[HistoricalOptionQuote] = []
        api_lookups = 0
        for item in pool:
            expiry = str(item.get('expiration_date', '')).replace('-', '')
            strike = float(item['strike_price'])
            ticker = str(item['ticker'])
            dte = (date.fromisoformat(str(item.get('expiration_date'))) - as_of_date).days
            close: float | None = None
            if not self.params.fast_mode and api_lookups < self.params.max_price_lookups:
                close = self.get_option_close(ticker, as_of)
                api_lookups += 1
            elif not self.params.fast_mode:
                close = None
            if close is None or close <= 0:
                if self.params.use_black_scholes_fallback:
                    close = option_price(spot, strike, dte, right, self.params.default_iv)
                else:
                    continue
            vol = estimate_vol_from_price(spot, strike, dte, right, close) if close > 0 else self.params.default_iv
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
        self._session_chain_cache[cache_key] = quotes
        return quotes
