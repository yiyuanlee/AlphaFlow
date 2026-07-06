"""Configuration loading, project paths, and script bootstrap."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Repository root (parent of alphaflow/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _is_project_root(directory: Path) -> bool:
    return (directory / "config.yaml").is_file() or (directory / "config" / "default.yaml").is_file()


def load_env_file(path: Path | None = None) -> None:
    """Load .env from project root (does not override existing env vars)."""
    env_path = (path or PROJECT_ROOT) / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def setup_project(caller_file: str | Path | None = None) -> Path:
    """Locate project root, load .env, and ensure root is on ``sys.path``.

    Used by ``scripts/_bootstrap.py`` for legacy ``python scripts/...`` runs.
    When the package is installed (``pip install -e .``), callers can skip this.
    """
    if caller_file is not None:
        start = Path(caller_file).resolve().parent
        for directory in (start, *start.parents):
            if _is_project_root(directory):
                load_env_file(directory)
                root = str(directory)
                if root not in sys.path:
                    sys.path.insert(0, root)
                return directory
        raise RuntimeError("AlphaFlow project root not found (missing config.yaml)")

    load_env_file(PROJECT_ROOT)
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return PROJECT_ROOT


# Load .env when the package is imported from a checkout.
load_env_file()


def output_path(name: str) -> Path:
    """Path under output/ for generated artifacts (charts, CSV, YAML)."""
    path = PROJECT_ROOT / "output" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def state_path(name: str) -> Path:
    """Path under state/ for live-trading runtime JSON."""
    path = PROJECT_ROOT / "state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def default_config_path() -> Path:
    split_default = CONFIG_DIR / "default.yaml"
    if split_default.is_file():
        return split_default
    return PROJECT_ROOT / "config.yaml"


@dataclass(frozen=True)
class StrategyParams:
    fast_period: int = 10
    slow_period: int = 25
    trend_period: int = 200
    rsi_period: int = 14
    rsi_upper: float = 65
    adx_period: int = 14
    adx_threshold: float = 20
    atr_period: int = 14
    atr_multiplier: float = 2.5
    vol_filter_period: int = 100
    vol_filter_ratio: float = 0.8
    trailing_atr_mult: float = 3.0
    trailing_stop: float = 0.12


@dataclass(frozen=True)
class RiskParams:
    risk_per_trade: float = 0.030
    alloc_index: float = 0.60
    alloc_stock: float = 0.40
    index_multiplier: float = 3.0


def load_config(path: str | Path | None = None, profile: str | None = None) -> dict[str, Any]:
    """Load configuration from a file or merged ``config/`` profiles."""
    if path is not None:
        return _load_yaml(Path(path))

    split_default = CONFIG_DIR / "default.yaml"
    if split_default.is_file():
        config = _load_yaml(split_default)
        if profile:
            profile_path = CONFIG_DIR / f"{profile}.yaml"
            if profile_path.is_file():
                config = _deep_merge(config, _load_yaml(profile_path))
        else:
            for name in ("equity", "options", "hot"):
                overlay_path = CONFIG_DIR / f"{name}.yaml"
                if overlay_path.is_file():
                    config = _deep_merge(config, _load_yaml(overlay_path))
        return config

    return _load_yaml(PROJECT_ROOT / "config.yaml")


def params_from_config(config: dict[str, Any]) -> tuple[StrategyParams, RiskParams]:
    s = config.get("strategy", {})
    r = config.get("risk", {})
    strategy = StrategyParams(
        fast_period=s.get("fast_period", 10),
        slow_period=s.get("slow_period", 25),
        trend_period=s.get("trend_period", 200),
        rsi_period=s.get("rsi_period", 14),
        rsi_upper=s.get("rsi_upper", 65),
        adx_period=s.get("adx_period", 14),
        adx_threshold=s.get("adx_threshold", 20),
        atr_period=s.get("atr_period", 14),
        atr_multiplier=s.get("atr_multiplier", 2.5),
        vol_filter_period=s.get("vol_filter_period", 100),
        vol_filter_ratio=s.get("vol_filter_ratio", 0.8),
        trailing_atr_mult=s.get("trailing_atr_mult", 3.0),
        trailing_stop=s.get("trailing_stop", 0.12),
    )
    risk = RiskParams(
        risk_per_trade=r.get("risk_per_trade", 0.030),
        alloc_index=r.get("alloc_index", 0.60),
        alloc_stock=r.get("alloc_stock", 0.40),
        index_multiplier=r.get("index_multiplier", 3.0),
    )
    return strategy, risk


def strategy_params_to_bt(strategy: StrategyParams, risk: RiskParams) -> dict[str, Any]:
    """Convert typed params to Backtrader strategy kwargs."""
    return {
        "fast_period": strategy.fast_period,
        "slow_period": strategy.slow_period,
        "trend_period": strategy.trend_period,
        "rsi_period": strategy.rsi_period,
        "rsi_upper": strategy.rsi_upper,
        "adx_period": strategy.adx_period,
        "adx_threshold": strategy.adx_threshold,
        "atr_period": strategy.atr_period,
        "atr_multiplier": strategy.atr_multiplier,
        "vol_filter_period": strategy.vol_filter_period,
        "vol_filter_ratio": strategy.vol_filter_ratio,
        "trailing_atr_mult": strategy.trailing_atr_mult,
        "trailing_stop": strategy.trailing_stop,
        "risk_per_trade": risk.risk_per_trade,
        "alloc_index": risk.alloc_index,
        "alloc_stock": risk.alloc_stock,
        "index_multiplier": risk.index_multiplier,
    }
