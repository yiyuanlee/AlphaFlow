"""Unattended shadow/paper orchestration for the isolated SPY scalper."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from alphaflow.scalping.alerts import ScalpAlertSink
from alphaflow.scalping.broker import StockBroker
from alphaflow.scalping.clock import ET, XnysClock
from alphaflow.scalping.config import ScalpConfig
from alphaflow.scalping.data import MinuteBarCache
from alphaflow.scalping.process_lock import ScalpProcessLock
from alphaflow.scalping.store import ScalpingStore
from alphaflow.scalping.strategy import (
    build_bracket_intent,
    compute_features,
    position_size,
    quote_is_executable,
    risk_per_share,
    signal_at,
)
from alphaflow.scalping.types import (
    ACTIVE_STOCK_ORDER_STATES,
    BracketIntent,
    BrokerStockOrder,
    ScalpAccountSnapshot,
    ScalpDirection,
    ScalpHealthSnapshot,
    ScalpPosition,
    ScalpPositionLifecycle,
    ScalpReconciliationResult,
    ScalpSignal,
    StockOrderLifecycle,
    StockOrderRecord,
    StockOrderRole,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class ScalpingService:
    def __init__(
        self,
        config: ScalpConfig,
        broker: StockBroker,
        store: ScalpingStore,
        alerts: ScalpAlertSink,
        *,
        clock: XnysClock | None = None,
        cache: MinuteBarCache | None = None,
    ) -> None:
        self.config = config
        self.broker = broker
        self.store = store
        self.alerts = alerts
        self.clock = clock or XnysClock()
        self.cache = cache or MinuteBarCache(config.backtest.cache_path)
        self._subscribed = False

    def doctor(self) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        config_errors = self.config.validate(require_account=True)
        checks["config"] = {"ok": not config_errors, "issues": config_errors}
        try:
            self._connect()
            account = self.broker.account_snapshot()
            account_issues = self._account_issues(account)
            checks["account"] = {
                "ok": not account_issues,
                "id": account.account_id,
                "paper": account.account_id.startswith("DU"),
                "net_liquidation": account.net_liquidation,
                "available_funds": account.available_funds,
                "buying_power": account.buying_power,
                "day_trades_remaining": account.day_trades_remaining,
                "account_type": account.account_type,
                "restrictions": list(account.trading_restrictions),
                "issues": account_issues,
            }
            positions = [position for position in self.broker.positions() if position.quantity]
            orders = [order for order in self.broker.orders() if order.status in ACTIVE_STOCK_ORDER_STATES]
            checks["isolation"] = {
                "ok": not positions and not orders,
                "positions": [asdict(position) for position in positions],
                "active_orders": [asdict(order) for order in orders],
            }
            quote = self.broker.quote(self.config.strategy.symbol)
            quote_ok, quote_reason = quote_is_executable(quote, datetime.now(timezone.utc), self.config.execution)
            checks["market_data"] = {
                "ok": quote_ok,
                "reason": quote_reason,
                "bid": quote.bid,
                "ask": quote.ask,
                "delayed": quote.delayed,
            }
            checks["shorting"] = {
                "ok": (quote.shortable_shares or 0) > 0 and not account.trading_restrictions,
                "shortable_shares": quote.shortable_shares,
            }
            self.broker.start_minute_subscription(self.config.strategy.symbol)
            self._subscribed = True
            bars = self.broker.complete_minute_bars()
            checks["minute_bars"] = {"ok": bool(bars), "complete_bars": len(bars)}
        except Exception as exc:
            logger.exception("Scalping doctor failed")
            checks["gateway"] = {"ok": False, "error": str(exc)}
        telegram_ok, telegram_message = self.alerts.probe()
        checks["telegram"] = {"ok": telegram_ok, "message": telegram_message}
        return {"ok": all(bool(check.get("ok")) for check in checks.values()), "checks": checks}

    def reconcile(self, *, halt_on_error: bool = True) -> ScalpReconciliationResult:
        self._connect()
        account = self.broker.account_snapshot()
        issues = self._account_issues(account)
        identity_failure = account.account_id != self.config.expected_account_id or not account.account_id.startswith(
            self.config.paper_account_prefixes
        )
        if identity_failure:
            result = ScalpReconciliationResult(
                ok=False,
                account_id=account.account_id,
                broker_quantity=0,
                local_quantity=0,
                active_orders=0,
                protected=False,
                issues=tuple(dict.fromkeys(issues)),
            )
            self.store.journal_event("reconcile", asdict(result))
            if halt_on_error:
                reason = "; ".join(result.issues)
                # Never issue cancel/order mutations after a live or wrong account is detected.
                self.store.set_halt(reason, self.config.persistence.halt_file)
                self.alerts.send("wrong_account", f"HALT: {reason}", critical=True)
            self.broker.disconnect()
            return result
        self.store.set_metadata("account_id", account.account_id)
        broker_positions = [position for position in self.broker.positions() if position.quantity]
        spy_positions = [position for position in broker_positions if position.symbol == self.config.strategy.symbol]
        for position in broker_positions:
            if position.symbol != self.config.strategy.symbol:
                issues.append(f"unknown broker position {position.symbol} {position.quantity}")
            if position.account_id != account.account_id:
                issues.append(f"position belongs to unexpected account {position.account_id}")
        broker_quantity = sum(position.quantity for position in spy_positions)
        self.store.set_metadata("broker_quantity", str(broker_quantity))

        broker_orders = self.broker.orders(include_completed=True)
        current_orders = [order for order in broker_orders if order.status in ACTIVE_STOCK_ORDER_STATES]
        known_current: list[BrokerStockOrder] = []
        for order in broker_orders:
            if order.symbol != self.config.strategy.symbol and order.status in ACTIVE_STOCK_ORDER_STATES:
                issues.append(f"unknown active stock order for {order.symbol}")
                continue
            if order.symbol != self.config.strategy.symbol:
                continue
            if not order.order_ref.startswith("AFSCALP-"):
                if order.status in ACTIVE_STOCK_ORDER_STATES:
                    issues.append(f"unknown/manual SPY order {order.broker_order_id}")
                continue
            local = self.store.order(order.order_ref)
            if local is None:
                if order.status in ACTIVE_STOCK_ORDER_STATES:
                    issues.append(f"broker orderRef is not reserved locally: {order.order_ref}")
                continue
            self.store.update_order(
                order.order_ref,
                status=order.status,
                broker_order_id=order.broker_order_id,
                perm_id=order.perm_id,
                filled_quantity=order.filled_quantity,
            )
            if order.status == StockOrderLifecycle.REJECTED.value:
                self.alerts.send(
                    f"order_rejected_{order.order_ref}",
                    f"Order rejected: {order.order_ref}",
                    critical=True,
                )
            if order.status in ACTIVE_STOCK_ORDER_STATES:
                known_current.append(order)

        for fill in self.broker.executions():
            resolved = fill
            if not fill.order_ref:
                matched = self.store.order_by_perm_id(fill.perm_id)
                if matched:
                    resolved = replace(fill, order_ref=matched.order_ref)
            if resolved.symbol != self.config.strategy.symbol:
                continue
            if not resolved.order_ref.startswith("AFSCALP-") or self.store.order(resolved.order_ref) is None:
                issues.append(f"unknown SPY execution {resolved.execution_id}")
                continue
            if self.store.record_fill(resolved):
                self.alerts.send(
                    f"fill_{resolved.execution_id}",
                    f"Fill {resolved.action} {resolved.quantity} {resolved.symbol} @ {resolved.price:.2f}",
                )

        local_position = self.store.open_position()
        if local_position is None and broker_quantity:
            local_position = self._recover_position(broker_quantity, known_current)
            if local_position is None:
                issues.append("SPY broker position cannot be recovered from exact local orderRef/permId records")

        if local_position is not None and broker_quantity == 0:
            if self._close_local_position(local_position):
                local_position = None
            else:
                issues.append("local SPY position disappeared without a matching exit execution")

        expected_quantity = _signed_quantity(local_position) if local_position else 0
        if broker_quantity != expected_quantity:
            issues.append(f"position mismatch: broker={broker_quantity}, local={expected_quantity}")

        protected = broker_quantity == 0 or self._is_protected(broker_quantity, local_position, current_orders)
        if broker_quantity and not protected:
            issues.append("open SPY position has no active, correctly-sized stop order")

        today_et = datetime.now(timezone.utc).astimezone(ET).date()
        if broker_quantity and (local_position is None or local_position.session_date != today_et):
            issues.append("overnight SPY position detected")

        result = ScalpReconciliationResult(
            ok=not issues,
            account_id=account.account_id,
            broker_quantity=broker_quantity,
            local_quantity=expected_quantity,
            active_orders=len(current_orders),
            protected=protected,
            issues=tuple(dict.fromkeys(issues)),
        )
        self.store.set_metadata("protected", "true" if protected else "false")
        self.store.journal_event("reconcile", asdict(result))
        if issues and halt_on_error:
            self._halt("; ".join(result.issues))
        return result

    def run_cycle(self, now_utc: datetime | None = None) -> ScalpHealthSnapshot:
        started = utc_now_iso()
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        details: dict[str, Any] = {}
        try:
            reconciliation = self.reconcile()
            details["reconciliation"] = asdict(reconciliation)
            if not self.broker.is_connected():
                self.store.set_metadata("connected", "false")
                self.store.heartbeat(self.config.persistence.heartbeat_file, "halted", details)
                self.store.record_cycle(started, "halted", details)
                return self.health_snapshot(connected=False)
            self._ensure_subscription()
            complete_bars = self.broker.complete_minute_bars(now)
            if complete_bars:
                self.cache.merge(complete_bars)
                self.store.set_metadata("last_complete_bar", complete_bars[-1].timestamp_utc.isoformat())
            self._cancel_stale_entries(now)

            local_position = self.store.open_position()
            if reconciliation.broker_quantity and not reconciliation.protected:
                self._emergency_flatten("unprotected position", now)
            elif local_position is not None:
                self._manage_open_position(local_position, reconciliation.broker_quantity, now)
            else:
                self._manage_shadow(now)
                if not self.store.halt_reason(self.config.persistence.halt_file):
                    self._evaluate_entry(now)
            self._mark_shadow_day_complete(now)
            status = "ok" if reconciliation.ok else "halted"
            self.store.set_metadata("connected", "true")
            self.store.heartbeat(self.config.persistence.heartbeat_file, status, details)
            self.store.record_cycle(started, status, details)
            return self.health_snapshot(connected=True)
        except Exception as exc:
            logger.exception("Scalping cycle failed")
            reason = f"cycle failure: {exc}"
            self._halt(reason)
            self.store.set_metadata("connected", "true" if self.broker.is_connected() else "false")
            self.store.heartbeat(self.config.persistence.heartbeat_file, "error", {"error": str(exc)})
            self.store.record_cycle(started, "error", {"error": str(exc)})
            return self.health_snapshot(connected=self.broker.is_connected())

    def run_daemon(self) -> None:
        with ScalpProcessLock(self.config.persistence.lock_file):
            self.alerts.send(
                "daemon_start",
                f"SPY scalper started in {'shadow' if self.config.shadow_mode else 'paper'} mode",
            )
            previously_connected = False
            try:
                while True:
                    snapshot = self.run_cycle()
                    if not snapshot.connected and previously_connected:
                        self.alerts.send("gateway_disconnected", "IB Gateway connection lost", critical=True)
                    elif snapshot.connected and not previously_connected:
                        self.alerts.send("gateway_recovered", "IB Gateway connection established")
                    previously_connected = snapshot.connected
                    if not snapshot.connected and (
                        "wrong account" in snapshot.halt_reason or "real/non-paper account" in snapshot.halt_reason
                    ):
                        return
                    self.broker.wait(self.config.execution.reconcile_interval_seconds)
            except KeyboardInterrupt:
                self.alerts.send("daemon_stop", "SPY scalper stopped by operator")
            finally:
                self.broker.disconnect()

    def manual_halt(self, reason: str) -> None:
        """Persist HALT immediately and cancel only known, unfilled entry orders when connected."""
        if not self.broker.is_connected():
            try:
                self.broker.connect()
            except (OSError, RuntimeError):
                self.store.set_halt(reason, self.config.persistence.halt_file)
                self.alerts.send("manual_halt", f"Manual HALT: {reason}", critical=True)
                return
        if self.broker.is_connected():
            account = self.broker.account_snapshot()
            if account.account_id != self.config.expected_account_id or not account.account_id.startswith(
                self.config.paper_account_prefixes
            ):
                self.store.set_halt(reason, self.config.persistence.halt_file)
                self.alerts.send("manual_halt", f"Manual HALT: {reason}", critical=True)
                return
        self._halt(reason)

    def manual_resume(self, confirm_account: str) -> ScalpReconciliationResult:
        expected = self.config.expected_account_id
        if not expected or confirm_account != expected:
            raise ValueError("account confirmation does not match IBKR_SCALP_PAPER_ACCOUNT")
        result = self.reconcile(halt_on_error=False)
        if not result.ok:
            return result
        self.store.clear_halt(self.config.persistence.halt_file)
        self.alerts.send("manual_resume", f"SPY scalper resumed for paper account {expected}")
        return result

    def health_snapshot(self, *, connected: bool | None = None) -> ScalpHealthSnapshot:
        position = self.store.open_position()
        now_et = datetime.now(timezone.utc).astimezone(ET)
        day_state = self.store.session_state(now_et.date()) if self.clock.is_session(now_et.date()) else {}
        halt_reason = self.store.halt_reason(self.config.persistence.halt_file)
        broker_quantity = int(self.store.get_metadata("broker_quantity", "0"))
        return ScalpHealthSnapshot(
            connected=self.broker.is_connected() if connected is None else connected,
            halted=bool(halt_reason),
            halt_reason=halt_reason,
            shadow_mode=self.config.shadow_mode,
            account_id=self.store.get_metadata("account_id"),
            broker_quantity=broker_quantity,
            local_quantity=_signed_quantity(position) if position else 0,
            active_orders=len(self.store.active_orders()),
            protected=broker_quantity == 0 or self.store.get_metadata("protected", "false") == "true",
            session_date=now_et.date().isoformat(),
            entries_today=int(day_state.get("entries", 0)),
            consecutive_losses=int(day_state.get("consecutive_losses", 0)),
            daily_locked=bool(day_state.get("daily_locked", 0)),
            shadow_sessions=self.store.shadow_sessions(),
            paper_sessions=self.store.paper_sessions(),
            closed_cycles=self.store.closed_cycles(),
            last_complete_bar=self.store.get_metadata("last_complete_bar"),
            last_heartbeat=self.store.get_metadata("last_heartbeat"),
            last_cycle_status=self.store.get_metadata("last_cycle_status"),
            details={},
        )

    def _connect(self) -> None:
        if not self.broker.is_connected():
            self.broker.connect()

    def _account_issues(self, account: ScalpAccountSnapshot) -> list[str]:
        issues = self.config.validate(require_account=True)
        expected = self.config.expected_account_id
        if account.account_id != expected:
            issues.append(f"wrong account: expected {expected or '<missing>'}, received {account.account_id}")
        if not account.account_id.startswith(self.config.paper_account_prefixes):
            issues.append("real/non-paper account detected")
        prior = self.store.get_metadata("account_id")
        if prior and prior != account.account_id:
            issues.append(f"database was previously bound to account {prior}")
        if account.net_liquidation <= 0 or account.available_funds <= 0:
            issues.append("invalid net liquidation or available funds")
        return issues

    def _ensure_subscription(self) -> None:
        if not self._subscribed:
            self.broker.start_minute_subscription(self.config.strategy.symbol)
            self._subscribed = True

    def _halt(self, reason: str) -> None:
        self.store.set_halt(reason, self.config.persistence.halt_file)
        broker_refs: set[str] = set()
        if self.broker.is_connected():
            try:
                broker_refs = {
                    order.order_ref for order in self.broker.orders() if order.status in ACTIVE_STOCK_ORDER_STATES
                }
            except RuntimeError:
                broker_refs = set()
        for order in self.store.active_orders():
            if (
                order.role == StockOrderRole.ENTRY.value
                and order.filled_quantity == 0
                and order.order_ref in broker_refs
            ):
                try:
                    self.broker.cancel(order.order_ref)
                except (KeyError, RuntimeError):
                    pass
        self.alerts.send("halt", f"HALT: {reason}", critical=True)

    def _recover_position(
        self,
        broker_quantity: int,
        current_orders: list[BrokerStockOrder],
    ) -> ScalpPosition | None:
        protected_intents: set[str] = set()
        for broker_order in current_orders:
            local = self.store.order(broker_order.order_ref)
            if local and local.role in {StockOrderRole.STOP_LOSS.value, StockOrderRole.TAKE_PROFIT.value}:
                protected_intents.add(local.intent_id)
        candidates = [
            entry
            for entry in self.store.recoverable_entries()
            if entry.intent_id in protected_intents
            and (entry.filled_quantity if entry.action == "BUY" else -entry.filled_quantity) == broker_quantity
        ]
        if len(candidates) != 1:
            return None
        entry = candidates[0]
        children = self.store.orders_for_intent(entry.intent_id)
        stop = next((order for order in children if order.role == StockOrderRole.STOP_LOSS.value), None)
        target = next((order for order in children if order.role == StockOrderRole.TAKE_PROFIT.value), None)
        if stop is None or target is None:
            return None
        fills = self.store.fills_for_refs({entry.order_ref})
        opened = _parse_timestamp(fills[-1].occurred_at) if fills else datetime.now(timezone.utc)
        position = ScalpPosition(
            intent_id=entry.intent_id,
            direction=ScalpDirection.LONG if entry.action == "BUY" else ScalpDirection.SHORT,
            symbol=entry.symbol,
            quantity=abs(broker_quantity),
            entry_price=entry.average_fill_price or (fills[-1].price if fills else entry.limit_price),
            stop_price=stop.stop_price,
            take_profit_price=target.limit_price,
            opened_at_utc=opened,
            session_date=opened.astimezone(ET).date(),
            entry_perm_id=entry.perm_id,
            stop_perm_id=stop.perm_id,
            take_profit_perm_id=target.perm_id,
        )
        self.store.save_position(position)
        self.alerts.send("position_recovered", f"Recovered {broker_quantity} SPY from {entry.intent_id}")
        return position

    def _close_local_position(self, position: ScalpPosition) -> bool:
        orders = self.store.orders_for_intent(position.intent_id)
        exit_refs = {order.order_ref for order in orders if order.role != StockOrderRole.ENTRY.value}
        entry_refs = {order.order_ref for order in orders if order.role == StockOrderRole.ENTRY.value}
        exits = self.store.fills_for_refs(exit_refs)
        entries = self.store.fills_for_refs(entry_refs)
        if not exits:
            return False
        exit_quantity = sum(fill.quantity for fill in exits)
        if exit_quantity < position.quantity:
            return False
        exit_price = sum(fill.price * fill.quantity for fill in exits) / exit_quantity
        commissions = sum(fill.commission for fill in [*entries, *exits])
        factor = 1.0 if position.direction is ScalpDirection.LONG else -1.0
        realized = factor * (exit_price - position.entry_price) * position.quantity - commissions
        position.state = ScalpPositionLifecycle.CLOSED.value
        position.closed_at_utc = max(_parse_timestamp(fill.occurred_at) for fill in exits)
        position.exit_price = exit_price
        position.realized_pnl = realized
        self.store.save_position(position)
        state = self.store.session_state(position.session_date)
        losses = int(state["consecutive_losses"]) + 1 if realized < 0 else 0
        updates: dict[str, Any] = {
            "realized_pnl": float(state["realized_pnl"]) + realized,
            "consecutive_losses": losses,
            "last_exit_at": position.closed_at_utc.isoformat(),
        }
        updates["rearmed_long" if position.direction is ScalpDirection.LONG else "rearmed_short"] = 0
        if losses >= self.config.strategy.max_consecutive_losses:
            updates["daily_locked"] = 1
        if float(state["opening_nlv"]) > 0 and float(updates["realized_pnl"]) <= -float(
            state["opening_nlv"]
        ) * self.config.risk.daily_loss_limit_pct:
            updates["daily_locked"] = 1
        self.store.update_session(position.session_date, **updates)
        self.alerts.send("position_closed", f"{position.intent_id} closed; P&L ${realized:.2f}")
        return True

    def _is_protected(
        self,
        broker_quantity: int,
        position: ScalpPosition | None,
        current_orders: list[BrokerStockOrder],
    ) -> bool:
        if position is None:
            return False
        expected_action = "SELL" if broker_quantity > 0 else "BUY"
        for broker_order in current_orders:
            local = self.store.order(broker_order.order_ref)
            if (
                local
                and local.intent_id == position.intent_id
                and local.role == StockOrderRole.STOP_LOSS.value
                and broker_order.action.upper() == expected_action
                and broker_order.quantity - broker_order.filled_quantity >= abs(broker_quantity)
                and broker_order.order_type.upper() in {"STP", "STOP"}
            ):
                if position.stop_perm_id != broker_order.perm_id:
                    position.stop_perm_id = broker_order.perm_id
                    self.store.save_position(position)
                return True
        return False

    def _cancel_stale_entries(self, now: datetime) -> None:
        for order in self.store.active_orders():
            if order.role != StockOrderRole.ENTRY.value or order.filled_quantity:
                continue
            created = _parse_timestamp(order.created_at)
            if (now - created).total_seconds() >= self.config.execution.entry_timeout_seconds:
                try:
                    self.broker.cancel(order.order_ref)
                    self.store.update_order(order.order_ref, status=StockOrderLifecycle.CANCELLED.value)
                except KeyError:
                    pass

    def _manage_open_position(self, position: ScalpPosition, broker_quantity: int, now: datetime) -> None:
        if broker_quantity == 0:
            return
        schedule = self.clock.schedule(position.session_date)
        reason = ""
        if schedule is None or now >= schedule.force_flat_at(self.config.execution.force_flat_minutes_before_close):
            reason = "session close"
        elif now >= position.opened_at_utc + timedelta(minutes=self.config.strategy.max_holding_minutes):
            reason = "20-minute time exit"
        quote = self.broker.quote(position.symbol)
        executable, quote_reason = quote_is_executable(quote, now, self.config.execution)
        if not executable:
            self.alerts.send("quote_invalid", f"Position quote invalid: {quote_reason}", critical=True)
        mark = quote.bid if broker_quantity > 0 else quote.ask
        state = self.store.session_state(position.session_date)
        factor = 1.0 if broker_quantity > 0 else -1.0
        unrealized = factor * (mark - position.entry_price) * abs(broker_quantity) if mark > 0 else 0.0
        day_pnl = float(state["realized_pnl"]) + unrealized
        if (
            float(state["opening_nlv"]) > 0
            and day_pnl <= -float(state["opening_nlv"]) * self.config.risk.daily_loss_limit_pct
        ):
            self.store.update_session(position.session_date, daily_locked=1)
            reason = "daily loss limit"
        if reason:
            self._flatten_position(position, reason, now)

    def _evaluate_entry(self, now: datetime) -> None:
        if not self.clock.session_for(now):
            return
        frame = self.cache.to_frame()
        if len(frame) < self.config.strategy.ema_slow + 1:
            return
        features = compute_features(frame, self.config.strategy)
        latest_timestamp = features.index[-1].to_pydatetime().astimezone(timezone.utc)
        if self.store.get_metadata("last_processed_bar") == latest_timestamp.isoformat():
            return
        self.store.set_metadata("last_processed_bar", latest_timestamp.isoformat())
        latest = features.iloc[-1]
        latest_session = latest["session_date"]
        self.store.session_state(latest_session)
        if not any(pd_is_missing(latest.get(name)) for name in ("opening_range_low", "opening_range_high")) and float(
            latest["opening_range_low"]
        ) <= float(latest["close"]) <= float(latest["opening_range_high"]):
            self.store.update_session(latest_session, rearmed_long=1, rearmed_short=1)
        elif len(features) > 1:
            previous = features.iloc[-2]
            if not any(
                pd_is_missing(previous.get(name)) for name in ("opening_range_low", "opening_range_high")
            ) and float(previous["opening_range_low"]) <= float(previous["close"]) <= float(
                previous["opening_range_high"]
            ):
                self.store.update_session(latest_session, rearmed_long=1, rearmed_short=1)
        signal = signal_at(features, len(features) - 1, self.config.strategy)
        if signal is None or signal.session_date != now.astimezone(ET).date():
            return
        account = self.broker.account_snapshot()
        state = self.store.session_state(signal.session_date, account.net_liquidation)
        if not self._entry_state_allows(signal, state, now):
            return
        quote = self.broker.quote(self.config.strategy.symbol)
        executable, reason = quote_is_executable(quote, now, self.config.execution)
        if not executable:
            self.alerts.send("quote_invalid", f"Signal skipped: {reason}", critical=True)
            return
        entry_price = quote.ask if signal.direction is ScalpDirection.LONG else quote.bid
        per_share = risk_per_share(entry_price, signal.atr14, self.config.risk)
        if per_share is None:
            self.store.journal_event("signal_skipped", {"reason": "stop exceeds 0.30%", "signal": asdict(signal)})
            return
        quantity = position_size(
            entry_price=entry_price,
            per_share_risk=per_share,
            opening_net_liquidation=float(state["opening_nlv"]),
            available_funds=min(account.available_funds, account.buying_power),
            config=self.config.risk,
        )
        if quantity <= 0:
            return
        if account.trading_restrictions:
            self.alerts.send(
                "account_restricted",
                f"Signal skipped due to IBKR restriction: {', '.join(account.trading_restrictions)}",
                critical=True,
            )
            return
        if signal.direction is ScalpDirection.SHORT and (quote.shortable_shares or 0) < quantity:
            self.alerts.send("short_unavailable", f"Short signal skipped; required {quantity} SPY shares")
            return
        intent = build_bracket_intent(signal, quote, quantity, per_share, self.config.risk, self.config.execution)
        self.store.update_session(signal.session_date, entries=int(state["entries"]) + 1)
        if self.config.shadow_mode:
            self._open_shadow(intent, signal, now)
            return
        self._submit_paper_bracket(intent, account)

    def _entry_state_allows(self, signal: ScalpSignal, state: dict[str, Any], now: datetime) -> bool:
        if bool(state["daily_locked"]):
            return False
        if int(state["entries"]) >= self.config.strategy.max_entries_per_day:
            return False
        if int(state["consecutive_losses"]) >= self.config.strategy.max_consecutive_losses:
            return False
        if self.store.active_orders() or self.store.open_position() is not None:
            return False
        if self.store.get_metadata("shadow_position"):
            return False
        last_exit = str(state["last_exit_at"])
        if last_exit and now < _parse_timestamp(last_exit) + timedelta(minutes=self.config.strategy.cooldown_minutes):
            return False
        rearm_key = "rearmed_long" if signal.direction is ScalpDirection.LONG else "rearmed_short"
        return bool(state[rearm_key])

    def _submit_paper_bracket(self, intent: BracketIntent, account: ScalpAccountSnapshot) -> None:
        if (
            self.config.mode != "paper"
            or not self.config.trading_enabled
            or self.config.shadow_mode
            or account.account_id != self.config.expected_account_id
            or not account.account_id.startswith("DU")
        ):
            self._halt("paper order safety gate rejected the bracket")
            return
        if self.store.shadow_sessions() < self.config.shadow_sessions_required:
            self._halt(f"requires {self.config.shadow_sessions_required} completed shadow sessions before paper orders")
            return
        if self.store.get_metadata("backtest_passed", "false") != "true":
            self._halt("the three-month full/OOS backtest gate has not passed")
            return
        if not self.store.reserve_bracket(intent):
            self._halt(f"duplicate intent/orderRef rejected: {intent.intent_id}")
            return
        try:
            broker_orders = self.broker.submit_bracket(intent)
            for order in broker_orders:
                self.store.update_order(
                    order.order_ref,
                    status=order.status,
                    broker_order_id=order.broker_order_id,
                    perm_id=order.perm_id,
                    filled_quantity=order.filled_quantity,
                )
            self.alerts.send("bracket_submitted", f"Submitted {intent.intent_id} for {intent.quantity} SPY")
        except Exception as exc:  # noqa: BLE001 - broker exceptions vary across ib_async callbacks
            for order_ref in (
                intent.parent_order_ref,
                intent.take_profit_order_ref,
                intent.stop_order_ref,
            ):
                self.store.update_order(order_ref, status=StockOrderLifecycle.REJECTED.value, last_error=str(exc))
            self._halt(f"bracket submission failed: {exc}")
            return
        elapsed = 0.0
        while elapsed < self.config.execution.entry_timeout_seconds:
            interval = min(
                float(self.config.execution.protection_timeout_seconds if elapsed == 0 else 1),
                self.config.execution.entry_timeout_seconds - elapsed,
            )
            self.broker.wait(interval)
            elapsed += interval
            filled_quantity = self._broker_spy_quantity()
            if filled_quantity and not self._intent_stop_is_active(intent, filled_quantity):
                self._emergency_flatten(
                    "filled bracket lacks stop protection within two seconds",
                    datetime.now(timezone.utc),
                )
                return
        parent = next(
            (order for order in self.broker.orders() if order.order_ref == intent.parent_order_ref),
            None,
        )
        if parent and parent.status in ACTIVE_STOCK_ORDER_STATES:
            self.broker.cancel(intent.parent_order_ref)
            self.alerts.send("entry_cancelled", f"Cancelled unfilled remainder of {intent.intent_id}")
        self.broker.wait(0.2)
        filled_quantity = self._broker_spy_quantity()
        if filled_quantity:
            for child_ref in (intent.take_profit_order_ref, intent.stop_order_ref):
                try:
                    child = self.broker.resize(child_ref, abs(filled_quantity))
                    self.store.update_order(
                        child_ref,
                        status=child.status,
                        broker_order_id=child.broker_order_id,
                        perm_id=child.perm_id,
                        filled_quantity=child.filled_quantity,
                    )
                except KeyError:
                    # The protection deadline below handles a child cancelled with the parent.
                    pass
        result = self.reconcile()
        if result.broker_quantity and not result.protected:
            self.broker.wait(self.config.execution.protection_timeout_seconds)
            result = self.reconcile(halt_on_error=False)
            if not result.protected:
                self._emergency_flatten("partial/full fill lacks stop protection", datetime.now(timezone.utc))

    def _intent_stop_is_active(self, intent: BracketIntent, broker_quantity: int) -> bool:
        expected_action = "SELL" if broker_quantity > 0 else "BUY"
        for order in self.broker.orders():
            if (
                order.order_ref == intent.stop_order_ref
                and order.status in ACTIVE_STOCK_ORDER_STATES
                and order.action.upper() == expected_action
                and order.order_type.upper() in {"STP", "STOP"}
                and order.quantity - order.filled_quantity >= abs(broker_quantity)
            ):
                return True
        return False

    def _flatten_position(self, position: ScalpPosition, reason: str, now: datetime) -> None:
        position.state = ScalpPositionLifecycle.FLATTENING.value
        self.store.save_position(position)
        self.alerts.send("flattening", f"Flattening {position.intent_id}: {reason}", critical=True)
        self.broker.cancel_symbol_orders(position.symbol)
        self.broker.wait(0.15)
        for attempt in range(1, self.config.execution.flatten_limit_attempts + 1):
            quantity = self._broker_spy_quantity()
            if quantity == 0:
                self.reconcile(halt_on_error=False)
                return
            quote = self.broker.quote(position.symbol)
            action = "SELL" if quantity > 0 else "BUY"
            price = quote.bid if quantity > 0 else quote.ask
            order_ref = f"{position.intent_id}-FL{attempt}"
            record = StockOrderRecord(
                intent_id=position.intent_id,
                order_ref=order_ref,
                parent_order_ref=position.intent_id,
                role=StockOrderRole.FLATTEN.value,
                action=action,
                symbol=position.symbol,
                quantity=abs(quantity),
                order_type="LMT",
                limit_price=price,
            )
            if not self.store.create_order(record):
                continue
            broker_order = self.broker.submit_exit_limit(position.symbol, action, abs(quantity), price, order_ref)
            self.store.update_order(
                order_ref,
                status=broker_order.status,
                broker_order_id=broker_order.broker_order_id,
                perm_id=broker_order.perm_id,
                filled_quantity=broker_order.filled_quantity,
            )
            self.broker.wait(self.config.execution.flatten_attempt_seconds)
            if self._broker_spy_quantity() == 0:
                self.reconcile(halt_on_error=False)
                return
            try:
                self.broker.cancel(order_ref)
            except KeyError:
                pass
        self._emergency_flatten(f"limit flatten failed: {reason}", now)

    def _emergency_flatten(self, reason: str, now: datetime) -> None:
        self._halt(reason)
        self.broker.cancel_symbol_orders(self.config.strategy.symbol)
        quantity = self._broker_spy_quantity()
        if quantity == 0:
            return
        action = "SELL" if quantity > 0 else "BUY"
        digest = now.strftime("%Y%m%d%H%M%S")
        order_ref = f"AFSCALP-EMERGENCY-{digest}"
        record = StockOrderRecord(
            intent_id=order_ref,
            order_ref=order_ref,
            parent_order_ref=order_ref,
            role=StockOrderRole.EMERGENCY.value,
            action=action,
            symbol=self.config.strategy.symbol,
            quantity=abs(quantity),
            order_type="MKT",
        )
        if self.store.create_order(record):
            order = self.broker.submit_emergency_market(self.config.strategy.symbol, action, abs(quantity), order_ref)
            self.store.update_order(
                order_ref,
                status=order.status,
                broker_order_id=order.broker_order_id,
                perm_id=order.perm_id,
                filled_quantity=order.filled_quantity,
            )
            self.alerts.send("emergency_market", f"Emergency market exit submitted: {reason}", critical=True)

    def _broker_spy_quantity(self) -> int:
        return sum(
            position.quantity for position in self.broker.positions() if position.symbol == self.config.strategy.symbol
        )

    def _open_shadow(self, intent: BracketIntent, signal: ScalpSignal, now: datetime) -> None:
        payload = {
            "intent": asdict(intent),
            "direction": signal.direction.value,
            "opened_at": now.isoformat(),
        }
        self.store.set_metadata("shadow_position", json.dumps(payload, default=_json_default))
        self.store.journal_event("shadow_bracket", payload)
        self.alerts.send("shadow_bracket", f"Shadow bracket {intent.intent_id} ({intent.direction.value})")

    def _manage_shadow(self, now: datetime) -> None:
        raw = self.store.get_metadata("shadow_position")
        if not raw:
            return
        payload = json.loads(raw)
        intent = payload["intent"]
        direction = ScalpDirection(payload["direction"])
        frame = self.cache.to_frame()
        if frame.empty:
            return
        opened = _parse_timestamp(payload["opened_at"])
        later = frame[frame.index > opened]
        if later.empty:
            return
        row = later.iloc[-1]
        timestamp = later.index[-1].to_pydatetime().astimezone(timezone.utc)
        schedule = self.clock.schedule(date.fromisoformat(intent["session_date"]))
        reason = ""
        exit_price = 0.0
        stop = float(intent["stop_price"])
        target = float(intent["take_profit_price"])
        if direction is ScalpDirection.LONG:
            if float(row["low"]) <= stop:
                reason, exit_price = "STOP", stop
            elif float(row["high"]) >= target:
                reason, exit_price = "TARGET", target
        else:
            if float(row["high"]) >= stop:
                reason, exit_price = "STOP", stop
            elif float(row["low"]) <= target:
                reason, exit_price = "TARGET", target
        if not reason and timestamp >= opened + timedelta(minutes=self.config.strategy.max_holding_minutes):
            reason, exit_price = "TIME", float(row["close"])
        if (
            schedule
            and not reason
            and timestamp >= schedule.force_flat_at(self.config.execution.force_flat_minutes_before_close)
        ):
            reason, exit_price = "SESSION_FLAT", float(row["close"])
        if not reason:
            return
        quantity = int(intent["quantity"])
        factor = 1.0 if direction is ScalpDirection.LONG else -1.0
        pnl = factor * (exit_price - float(intent["entry_limit"])) * quantity
        session_date = date.fromisoformat(intent["session_date"])
        state = self.store.session_state(session_date)
        losses = int(state["consecutive_losses"]) + 1 if pnl < 0 else 0
        updates: dict[str, Any] = {
            "realized_pnl": float(state["realized_pnl"]) + pnl,
            "consecutive_losses": losses,
            "last_exit_at": timestamp.isoformat(),
        }
        updates["rearmed_long" if direction is ScalpDirection.LONG else "rearmed_short"] = 0
        if losses >= self.config.strategy.max_consecutive_losses:
            updates["daily_locked"] = 1
        if (
            float(state["opening_nlv"]) > 0
            and float(updates["realized_pnl"]) <= -float(state["opening_nlv"]) * self.config.risk.daily_loss_limit_pct
        ):
            updates["daily_locked"] = 1
        self.store.update_session(session_date, **updates)
        self.store.set_metadata("shadow_position", "")
        self.store.journal_event("shadow_close", {"intent_id": intent["intent_id"], "reason": reason, "pnl": pnl})

    def _mark_shadow_day_complete(self, now: datetime) -> None:
        local_date = now.astimezone(ET).date()
        schedule = self.clock.schedule(local_date)
        if schedule is None or now < schedule.force_flat_at(self.config.execution.force_flat_minutes_before_close):
            return
        state = self.store.session_state(local_date)
        if self.config.shadow_mode and not state["shadow_complete"]:
            self.store.update_session(local_date, shadow_complete=1)
        if self.store.get_metadata("last_daily_summary") != local_date.isoformat():
            mode = "Shadow" if self.config.shadow_mode else "Paper"
            self.alerts.send(
                f"daily_summary_{local_date.isoformat()}",
                f"{mode} day complete: entries={state['entries']}, realized=${state['realized_pnl']:.2f}",
            )
            self.store.set_metadata("last_daily_summary", local_date.isoformat())
            if local_date.weekday() == 4:
                self.alerts.send(
                    f"gateway_auth_reminder_{local_date.isoformat()}",
                    "Weekend reminder: verify the dedicated paper Gateway can re-authenticate before Monday.",
                )


def _signed_quantity(position: ScalpPosition | None) -> int:
    if position is None:
        return 0
    return position.quantity if position.direction is ScalpDirection.LONG else -position.quantity


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, ScalpDirection):
        return value.value
    return str(value)


def pd_is_missing(value: Any) -> bool:
    """Avoid importing pandas into the orchestration module for two scalar checks."""
    if value is None:
        return True
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False
