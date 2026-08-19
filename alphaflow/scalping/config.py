"""Typed configuration and hard safety rails for the SPY paper scalper."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alphaflow.core.config import PROJECT_ROOT


@dataclass(frozen=True)
class ScalpBrokerConfig:
    host: str = "127.0.0.1"
    port: int = 4004
    client_id: int = 4
    connect_timeout: int = 10


@dataclass(frozen=True)
class OrbStrategyConfig:
    symbol: str = "SPY"
    timezone: str = "America/New_York"
    opening_range_start: str = "09:30"
    opening_range_end: str = "09:45"
    entry_start: str = "09:45"
    entry_end: str = "11:30"
    breakout_buffer: float = 0.01
    ema_fast: int = 9
    ema_slow: int = 21
    atr_period: int = 14
    relative_volume_period: int = 20
    relative_volume_min_periods: int = 15
    relative_volume_threshold: float = 1.5
    max_entries_per_day: int = 5
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 5
    max_holding_minutes: int = 20


@dataclass(frozen=True)
class ScalpRiskConfig:
    risk_per_trade_pct: float = 0.002
    daily_loss_limit_pct: float = 0.01
    minimum_stop_pct: float = 0.001
    atr_stop_multiple: float = 0.5
    maximum_stop_pct: float = 0.003
    target_multiple: float = 1.5
    max_notional_pct: float = 1.0
    allow_leverage: bool = False


@dataclass(frozen=True)
class ScalpExecutionConfig:
    quote_max_age_seconds: int = 2
    max_spread: float = 0.03
    entry_timeout_seconds: int = 5
    protection_timeout_seconds: int = 2
    reconcile_interval_seconds: int = 5
    loop_interval_seconds: int = 5
    flatten_limit_attempts: int = 2
    flatten_attempt_seconds: int = 5
    force_flat_minutes_before_close: int = 15
    tick_size: float = 0.01
    allow_delayed_data: bool = False
    emergency_market_exit: bool = True


@dataclass(frozen=True)
class ScalpBacktestConfig:
    cache_path: Path = PROJECT_ROOT / "output" / "scalping_cache" / "SPY_1m.csv.gz"
    initial_equity: float = 100_000.0
    commission_per_share: float = 0.005
    minimum_commission: float = 1.0
    adverse_slippage_bps: float = 1.0
    validation_months: int = 2
    out_of_sample_months: int = 1
    minimum_total_trades: int = 60
    minimum_out_of_sample_trades: int = 15
    minimum_profit_factor: float = 1.10
    maximum_drawdown_pct: float = 5.0


@dataclass(frozen=True)
class ScalpPersistenceConfig:
    database: Path = PROJECT_ROOT / "state" / "scalper.db"
    journal: Path = PROJECT_ROOT / "output" / "spy_orb.jsonl"
    halt_file: Path = PROJECT_ROOT / "state" / "SCALP_HALT"
    lock_file: Path = PROJECT_ROOT / "state" / ".alphaflow-scalp.lock"
    heartbeat_file: Path = PROJECT_ROOT / "state" / "scalp-heartbeat.json"


@dataclass(frozen=True)
class ScalpAlertConfig:
    telegram_token_env: str = "ALPHAFLOW_TELEGRAM_BOT_TOKEN"
    telegram_chat_id_env: str = "ALPHAFLOW_TELEGRAM_CHAT_ID"
    dedupe_minutes: int = 15
    heartbeat_stale_seconds: int = 180


@dataclass(frozen=True)
class ScalpConfig:
    broker: ScalpBrokerConfig = field(default_factory=ScalpBrokerConfig)
    strategy: OrbStrategyConfig = field(default_factory=OrbStrategyConfig)
    risk: ScalpRiskConfig = field(default_factory=ScalpRiskConfig)
    execution: ScalpExecutionConfig = field(default_factory=ScalpExecutionConfig)
    backtest: ScalpBacktestConfig = field(default_factory=ScalpBacktestConfig)
    persistence: ScalpPersistenceConfig = field(default_factory=ScalpPersistenceConfig)
    alerts: ScalpAlertConfig = field(default_factory=ScalpAlertConfig)
    mode: str = "paper"
    trading_enabled: bool = False
    shadow_mode: bool = True
    shadow_sessions_required: int = 5
    account_id_env: str = "IBKR_SCALP_PAPER_ACCOUNT"
    paper_account_prefixes: tuple[str, ...] = ("DU",)

    @property
    def expected_account_id(self) -> str:
        return os.environ.get(self.account_id_env, "").strip()

    def validate(self, *, require_account: bool = True) -> list[str]:
        errors: list[str] = []
        if self.mode != "paper":
            errors.append("scalping mode must be paper")
        if self.strategy.symbol != "SPY":
            errors.append("the scalping pilot only permits SPY")
        if self.broker.port != 4004 or self.broker.client_id != 4:
            errors.append("the isolated scalping Gateway must use port 4004 and client_id 4")
        if self.paper_account_prefixes != ("DU",):
            errors.append("paper account prefix must be exactly DU")
        if require_account and not self.expected_account_id:
            errors.append(f"missing environment variable {self.account_id_env}")
        elif self.expected_account_id and not self.expected_account_id.startswith(self.paper_account_prefixes):
            errors.append("configured scalping account does not look like an IBKR paper account")
        if self.trading_enabled and self.shadow_mode:
            errors.append("trading_enabled and shadow_mode cannot both be true")
        if self.risk.allow_leverage or self.risk.max_notional_pct > 1.0:
            errors.append("leverage is forbidden and the notional cap cannot exceed 100% of NLV")
        if self.risk.risk_per_trade_pct > 0.002:
            errors.append("per-trade risk cannot exceed 0.20%")
        if self.risk.daily_loss_limit_pct > 0.01:
            errors.append("daily loss limit cannot exceed 1.00%")
        if self.strategy.max_entries_per_day > 5:
            errors.append("daily entries cannot exceed five")
        if self.strategy.max_consecutive_losses > 3:
            errors.append("daily consecutive-loss limit cannot exceed three")
        if self.execution.allow_delayed_data:
            errors.append("delayed market data is not permitted")
        if self.execution.reconcile_interval_seconds > 5:
            errors.append("broker reconciliation interval cannot exceed five seconds")
        if not self.execution.emergency_market_exit:
            errors.append("emergency market flattening must remain enabled")
        return errors


def _path(value: str, default: str) -> Path:
    path = Path(value or default)
    return path if path.is_absolute() else PROJECT_ROOT / path


def scalp_config_from_yaml(config: dict[str, Any]) -> ScalpConfig:
    raw = config.get("scalping", {})
    broker = raw.get("broker", {})
    strategy = raw.get("strategy", {})
    risk = raw.get("risk", {})
    execution = raw.get("execution", {})
    backtest = raw.get("backtest", {})
    persistence = raw.get("persistence", {})
    alerts = raw.get("alerts", {})
    return ScalpConfig(
        mode=str(raw.get("mode", "paper")),
        trading_enabled=bool(raw.get("trading_enabled", False)),
        shadow_mode=bool(raw.get("shadow_mode", True)),
        shadow_sessions_required=int(raw.get("shadow_sessions_required", 5)),
        account_id_env=str(raw.get("account_id_env", "IBKR_SCALP_PAPER_ACCOUNT")),
        paper_account_prefixes=tuple(raw.get("paper_account_prefixes", ["DU"])),
        broker=ScalpBrokerConfig(
            host=str(broker.get("host", "127.0.0.1")),
            port=int(broker.get("port", 4004)),
            client_id=int(broker.get("client_id", 4)),
            connect_timeout=int(broker.get("connect_timeout", 10)),
        ),
        strategy=OrbStrategyConfig(
            symbol=str(strategy.get("symbol", "SPY")),
            timezone=str(strategy.get("timezone", "America/New_York")),
            opening_range_start=str(strategy.get("opening_range_start", "09:30")),
            opening_range_end=str(strategy.get("opening_range_end", "09:45")),
            entry_start=str(strategy.get("entry_start", "09:45")),
            entry_end=str(strategy.get("entry_end", "11:30")),
            breakout_buffer=float(strategy.get("breakout_buffer", 0.01)),
            ema_fast=int(strategy.get("ema_fast", 9)),
            ema_slow=int(strategy.get("ema_slow", 21)),
            atr_period=int(strategy.get("atr_period", 14)),
            relative_volume_period=int(strategy.get("relative_volume_period", 20)),
            relative_volume_min_periods=int(strategy.get("relative_volume_min_periods", 15)),
            relative_volume_threshold=float(strategy.get("relative_volume_threshold", 1.5)),
            max_entries_per_day=int(strategy.get("max_entries_per_day", 5)),
            max_consecutive_losses=int(strategy.get("max_consecutive_losses", 3)),
            cooldown_minutes=int(strategy.get("cooldown_minutes", 5)),
            max_holding_minutes=int(strategy.get("max_holding_minutes", 20)),
        ),
        risk=ScalpRiskConfig(
            risk_per_trade_pct=float(risk.get("risk_per_trade_pct", 0.002)),
            daily_loss_limit_pct=float(risk.get("daily_loss_limit_pct", 0.01)),
            minimum_stop_pct=float(risk.get("minimum_stop_pct", 0.001)),
            atr_stop_multiple=float(risk.get("atr_stop_multiple", 0.5)),
            maximum_stop_pct=float(risk.get("maximum_stop_pct", 0.003)),
            target_multiple=float(risk.get("target_multiple", 1.5)),
            max_notional_pct=float(risk.get("max_notional_pct", 1.0)),
            allow_leverage=bool(risk.get("allow_leverage", False)),
        ),
        execution=ScalpExecutionConfig(
            quote_max_age_seconds=int(execution.get("quote_max_age_seconds", 2)),
            max_spread=float(execution.get("max_spread", 0.03)),
            entry_timeout_seconds=int(execution.get("entry_timeout_seconds", 5)),
            protection_timeout_seconds=int(execution.get("protection_timeout_seconds", 2)),
            reconcile_interval_seconds=int(execution.get("reconcile_interval_seconds", 5)),
            loop_interval_seconds=int(execution.get("loop_interval_seconds", 5)),
            flatten_limit_attempts=int(execution.get("flatten_limit_attempts", 2)),
            flatten_attempt_seconds=int(execution.get("flatten_attempt_seconds", 5)),
            force_flat_minutes_before_close=int(execution.get("force_flat_minutes_before_close", 15)),
            tick_size=float(execution.get("tick_size", 0.01)),
            allow_delayed_data=bool(execution.get("allow_delayed_data", False)),
            emergency_market_exit=bool(execution.get("emergency_market_exit", True)),
        ),
        backtest=ScalpBacktestConfig(
            cache_path=_path(str(backtest.get("cache_path", "")), "output/scalping_cache/SPY_1m.csv.gz"),
            initial_equity=float(backtest.get("initial_equity", 100_000.0)),
            commission_per_share=float(backtest.get("commission_per_share", 0.005)),
            minimum_commission=float(backtest.get("minimum_commission", 1.0)),
            adverse_slippage_bps=float(backtest.get("adverse_slippage_bps", 1.0)),
            validation_months=int(backtest.get("validation_months", 2)),
            out_of_sample_months=int(backtest.get("out_of_sample_months", 1)),
            minimum_total_trades=int(backtest.get("minimum_total_trades", 60)),
            minimum_out_of_sample_trades=int(backtest.get("minimum_out_of_sample_trades", 15)),
            minimum_profit_factor=float(backtest.get("minimum_profit_factor", 1.10)),
            maximum_drawdown_pct=float(backtest.get("maximum_drawdown_pct", 5.0)),
        ),
        persistence=ScalpPersistenceConfig(
            database=_path(str(persistence.get("database", "")), "state/scalper.db"),
            journal=_path(str(persistence.get("journal", "")), "output/spy_orb.jsonl"),
            halt_file=_path(str(persistence.get("halt_file", "")), "state/SCALP_HALT"),
            lock_file=_path(str(persistence.get("lock_file", "")), "state/.alphaflow-scalp.lock"),
            heartbeat_file=_path(str(persistence.get("heartbeat_file", "")), "state/scalp-heartbeat.json"),
        ),
        alerts=ScalpAlertConfig(
            telegram_token_env=str(alerts.get("telegram_token_env", "ALPHAFLOW_TELEGRAM_BOT_TOKEN")),
            telegram_chat_id_env=str(alerts.get("telegram_chat_id_env", "ALPHAFLOW_TELEGRAM_CHAT_ID")),
            dedupe_minutes=int(alerts.get("dedupe_minutes", 15)),
            heartbeat_stale_seconds=int(alerts.get("heartbeat_stale_seconds", 180)),
        ),
    )
