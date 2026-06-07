"""Tests for Polygon provider response parsing."""

from alphaflow.options.chain_data.polygon import PolygonChainProvider
from alphaflow.options.options_config import OptionsChainDataParams


class _FakePolygon(PolygonChainProvider):
    def __init__(self):
        super().__init__(OptionsChainDataParams(provider='polygon', api_key_env='POLYGON_API_KEY'))
        self.api_key = 'test'
        self.responses: dict[str, dict] = {}

    def _get_json(self, path: str, query: dict | None = None) -> dict:
        if path in self.responses:
            return self.responses[path]
        if query:
            key = f'{path}?{sorted(query.items())}'
            if key in self.responses:
                return self.responses[key]
        return {}


def test_option_close_uses_open_close_first():
    provider = _FakePolygon()
    provider.responses['/v1/open-close/O:QQQ240315P00400000/2024-01-15'] = {
        'status': 'OK',
        'close': 2.45,
    }
    assert provider.get_option_close('O:QQQ240315P00400000', '2024-01-15') == 2.45


def test_option_close_falls_back_to_aggs():
    provider = _FakePolygon()
    provider.responses['/v1/open-close/O:QQQ240315P00400000/2024-01-15'] = {'status': 'NOT_FOUND'}
    provider.responses['/v2/aggs/ticker/O:QQQ240315P00400000/range/1/day/2024-01-15/2024-01-15'] = {
        'results': [{'c': 1.88}],
    }
    assert provider.get_option_close('QQQ240315P00400000', '2024-01-15') == 1.88


def test_strike_otm_band_puts():
    provider = _FakePolygon()
    assert provider._strike_in_otm_band(380, 400, 'P') is True
    assert provider._strike_in_otm_band(410, 400, 'P') is False
