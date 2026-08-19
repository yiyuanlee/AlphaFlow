"""Typed configuration for the V11 unattended paper profile."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alphaflow.core.config import PROJECT_ROOT


@dataclass(frozen=True)
class BrokerConfig:
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 3
    connect_timeout: int = 10


@dataclass(frozen=True)
class CoveredCallConfig:
    symbol: str = "QQQ"
    required_shares: int = 100
    contracts: int = 1
    trend_period: int = 200
    dte_min: int = 21
    dte_max: int = 45
    delta_target: float = 0.25
    profit_take_pct: float = 0.50
    force_exit_dte: int = 7


@dataclass(frozen=True)
class ScheduleConfig:
    timezone: str = "America/New_York"
    entry_start: str = "10:00"
    entry_end: str = "11:00"
    manage_start: str = "09:35"
    manage_end: str = "15:45"
    monitor_interval_seconds: int = 60
    exit_retry_seconds: int = 300


@dataclass(frozen=True)
class SafeExecutionConfig:
    order_type: str = "limit"
    tif: str = "DAY"
    quote_max_age_seconds: int = 10
    max_bid_ask_spread_pct: float = 0.15
    reprice_interval_seconds: int = 60
    max_entry_attempts: int = 3
    max_exit_attempts_per_cycle: int = 3
    tick_size: float = 0.01
    allow_delayed_data: bool = False


@dataclass(frozen=True)
class PersistenceConfig:
    database: Path = PROJECT_ROOT / "state" / "alphaflow.db"
    journal: Path = PROJECT_ROOT / "output" / "unattended_paper.jsonl"
    halt_file: Path = PROJECT_ROOT / "state" / "HALT"
    lock_file: Path = PROJECT_ROOT / "state" / ".alphaflow-v11.lock"


@dataclass(frozen=True)
class AlertConfig:
    telegram_token_env: str = "ALPHAFLOW_TELEGRAM_BOT_TOKEN"
    telegram_chat_id_env: str = "ALPHAFLOW_TELEGRAM_CHAT_ID"
    dedupe_minutes: int = 15
    heartbeat_stale_seconds: int = 180


@dataclass(frozen=True)
class UnattendedPaperConfig:
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    strategy: CoveredCallConfig = field(default_factory=CoveredCallConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    execution: SafeExecutionConfig = field(default_factory=SafeExecutionConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    mode: str = "paper"
    trading_enabled: bool = False
    shadow_mode: bool = True
    shadow_sessions_required: int = 5
    account_id_env: str = "IBKR_PAPER_ACCOUNT"
    paper_account_prefixes: tuple[str, ...] = ("DU",)

    @property
    def expected_account_id(self) -> str:
        return os.environ.get(self.account_id_env, "").strip()

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.mode != "paper":
            errors.append("mode must be paper")
        if self.strategy.symbol != "QQQ":
            errors.append("V11 pilot only permits QQQ")
        if self.strategy.contracts != 1 or self.strategy.required_shares < 100:
            errors.append("V11 pilot requires exactly one contract backed by at least 100 shares")
        if self.broker.port != 4002:
            errors.append("paper IB Gateway must use port 4002")
        if self.broker.client_id != 3:
            errors.append("unattended paper trading must use client_id 3")
        if self.paper_account_prefixes != ("DU",):
            errors.append("paper account prefix must be exactly DU")
        if not self.expected_account_id:
            errors.append(f"missing environment variable {self.account_id_env}")
        elif not self.expected_account_id.startswith(self.paper_account_prefixes):
            errors.append("configured account does not look like an IBKR paper account")
        if self.execution.order_type.lower() != "limit":
            errors.append("only limit orders are permitted")
        if self.execution.tif.upper() != "DAY":
            errors.append("only DAY orders are permitted")
        if self.execution.allow_delayed_data:
            errors.append("delayed market data is not permitted")
        if self.strategy.profit_take_pct != 0.50:
            errors.append("V11 pilot profit target must remain 50%")
        if self.strategy.force_exit_dte != 7:
            errors.append("V11 pilot force exit must remain 7 DTE")
        return errors


def _path(value: str, default: str) -> Path:
    path = Path(value or default)
    return path if path.is_absolute() else PROJECT_ROOT / path


def unattended_config_from_yaml(config: dict[str, Any]) -> UnattendedPaperConfig:
    raw = config.get("unattended_paper", {})
    broker = raw.get("broker", {})
    strategy = raw.get("strategy", {})
    schedule = raw.get("schedule", {})
    execution = raw.get("execution", {})
    persistence = raw.get("persistence", {})
    alerts = raw.get("alerts", {})
    return UnattendedPaperConfig(
        mode=str(raw.get("mode", "paper")),
        trading_enabled=bool(raw.get("trading_enabled", False)),
        shadow_mode=bool(raw.get("shadow_mode", True)),
        shadow_sessions_required=int(raw.get("shadow_sessions_required", 5)),
        account_id_env=str(raw.get("account_id_env", "IBKR_PAPER_ACCOUNT")),
        paper_account_prefixes=tuple(raw.get("paper_account_prefixes", ["DU"])),
        broker=BrokerConfig(
            host=str(broker.get("host", "127.0.0.1")),
            port=int(broker.get("port", 4002)),
            client_id=int(broker.get("client_id", 3)),
            connect_timeout=int(broker.get("connect_timeout", 10)),
        ),
        strategy=CoveredCallConfig(
            symbol=str(strategy.get("symbol", "QQQ")),
            required_shares=int(strategy.get("required_shares", 100)),
            contracts=int(strategy.get("contracts", 1)),
            trend_period=int(strategy.get("trend_period", 200)),
            dte_min=int(strategy.get("dte_min", 21)),
            dte_max=int(strategy.get("dte_max", 45)),
            delta_target=float(strategy.get("delta_target", 0.25)),
            profit_take_pct=float(strategy.get("profit_take_pct", 0.50)),
            force_exit_dte=int(strategy.get("force_exit_dte", 7)),
        ),
        schedule=ScheduleConfig(
            timezone=str(schedule.get("timezone", "America/New_York")),
            entry_start=str(schedule.get("entry_start", "10:00")),
            entry_end=str(schedule.get("entry_end", "11:00")),
            manage_start=str(schedule.get("manage_start", "09:35")),
            manage_end=str(schedule.get("manage_end", "15:45")),
            monitor_interval_seconds=int(schedule.get("monitor_interval_seconds", 60)),
            exit_retry_seconds=int(schedule.get("exit_retry_seconds", 300)),
        ),
        execution=SafeExecutionConfig(
            order_type=str(execution.get("order_type", "limit")),
            tif=str(execution.get("tif", "DAY")),
            quote_max_age_seconds=int(execution.get("quote_max_age_seconds", 10)),
            max_bid_ask_spread_pct=float(execution.get("max_bid_ask_spread_pct", 0.15)),
            reprice_interval_seconds=int(execution.get("reprice_interval_seconds", 60)),
            max_entry_attempts=int(execution.get("max_entry_attempts", 3)),
            max_exit_attempts_per_cycle=int(execution.get("max_exit_attempts_per_cycle", 3)),
            tick_size=float(execution.get("tick_size", 0.01)),
            allow_delayed_data=bool(execution.get("allow_delayed_data", False)),
        ),
        persistence=PersistenceConfig(
            database=_path(str(persistence.get("database", "")), "state/alphaflow.db"),
            journal=_path(str(persistence.get("journal", "")), "output/unattended_paper.jsonl"),
            halt_file=_path(str(persistence.get("halt_file", "")), "state/HALT"),
            lock_file=_path(str(persistence.get("lock_file", "")), "state/.alphaflow-v11.lock"),
        ),
        alerts=AlertConfig(
            telegram_token_env=str(alerts.get("telegram_token_env", "ALPHAFLOW_TELEGRAM_BOT_TOKEN")),
            telegram_chat_id_env=str(alerts.get("telegram_chat_id_env", "ALPHAFLOW_TELEGRAM_CHAT_ID")),
            dedupe_minutes=int(alerts.get("dedupe_minutes", 15)),
            heartbeat_stale_seconds=int(alerts.get("heartbeat_stale_seconds", 180)),
        ),
    )
