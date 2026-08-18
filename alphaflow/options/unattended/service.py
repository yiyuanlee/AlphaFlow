"""Fail-closed unattended QQQ covered-call orchestration."""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from alphaflow.core.persistence.journal import append_event

from .alerts import AlertSink
from .broker import Broker
from .config import UnattendedPaperConfig
from .market_clock import MarketClock
from .process_lock import ProcessLock
from .store import UnattendedStore
from .strategy import (
    completed_bar_diagnostics,
    exit_reason,
    make_intent,
    next_limit_price,
    quote_age_seconds,
    select_covered_call_quote,
)
from .types import (
    BrokerOrder,
    BrokerPosition,
    HealthSnapshot,
    OptionMarketQuote,
    OrderLifecycle,
    OrderRecord,
    PositionLifecycle,
    ReconciliationResult,
    TradeIntent,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


def _is_sell(action: str) -> bool:
    return action.upper() in {"SELL", "SLD"}


def _is_buy(action: str) -> bool:
    return action.upper() in {"BUY", "BOT"}


class UnattendedService:
    def __init__(
        self,
        config: UnattendedPaperConfig,
        broker: Broker,
        store: UnattendedStore,
        alerts: AlertSink,
        clock: MarketClock | None = None,
    ):
        self.config = config
        self.broker = broker
        self.store = store
        self.alerts = alerts
        self.clock = clock or MarketClock(config.schedule)
        self._last_reconciliation: ReconciliationResult | None = None

    def _event(self, event: str, **fields: object) -> None:
        append_event(self.config.persistence.journal, event, **fields)

    def _ensure_connected(self) -> None:
        if not self.broker.is_connected():
            previous = self.store.get_meta("broker_connection", {})
            self.broker.connect()
            self._event("broker_connected", host=self.config.broker.host, port=self.config.broker.port)
            if previous.get("status") == "disconnected":
                self.alerts.send("broker_recovered", "IB Gateway paper connection recovered")
            else:
                self.alerts.send("broker_connected", "Connected to IB Gateway paper session")
            self.store.set_meta("broker_connection", {"status": "connected", "at": utc_now_iso()})

    def _account_is_authorized(self, account_id: str) -> bool:
        expected = self.config.expected_account_id
        return bool(expected) and account_id == expected and account_id.startswith("DU")

    def _validate_account(self, account_id: str) -> list[str]:
        issues = self.config.validate()
        expected = self.config.expected_account_id
        if account_id != expected:
            issues.append(f"connected account {account_id!r} does not match configured paper account")
        if not account_id.startswith(self.config.paper_account_prefixes):
            issues.append(f"connected account {account_id!r} is not an allowed paper account")
        return issues

    @staticmethod
    def _qqq_exposure(positions: list[BrokerPosition], symbol: str) -> tuple[int, list[BrokerPosition]]:
        stock_shares = int(
            sum(position.quantity for position in positions if position.symbol == symbol and position.security_type == "STK")
        )
        calls = [
            position
            for position in positions
            if position.symbol == symbol
            and position.security_type == "OPT"
            and position.right.upper() == "C"
            and position.quantity < 0
        ]
        return stock_shares, calls

    def _record_broker_order(self, broker_order: BrokerOrder) -> OrderRecord:
        record = self.store.get_order(order_ref=broker_order.order_ref)
        if record is None:
            purpose = "entry" if _is_sell(broker_order.action) else "exit"
            record = OrderRecord(
                intent_id=f"recovered:{broker_order.order_ref}",
                order_ref=broker_order.order_ref,
                purpose=purpose,
                action="SELL" if _is_sell(broker_order.action) else "BUY",
                symbol=broker_order.symbol,
                quantity=broker_order.quantity,
                limit_price=broker_order.limit_price,
                status=broker_order.status,
                expiry=broker_order.expiry,
                strike=broker_order.strike,
                right=broker_order.right or "C",
                con_id=broker_order.con_id,
                broker_order_id=broker_order.broker_order_id,
                perm_id=broker_order.perm_id,
                filled_quantity=broker_order.filled_quantity,
                attempts=1,
            )
            self.store.upsert_order(record)
            if record.status == OrderLifecycle.REJECTED.value:
                self.alerts.send(
                    f"order_rejected:{record.order_ref}",
                    f"Broker rejected recovered order {record.order_ref}",
                    critical=True,
                )
            return record
        previous_status = record.status
        updated = self.store.update_order(
            record.intent_id,
            status=broker_order.status,
            broker_order_id=broker_order.broker_order_id,
            perm_id=broker_order.perm_id,
            filled_quantity=broker_order.filled_quantity,
            limit_price=broker_order.limit_price,
        )
        if updated.status == OrderLifecycle.REJECTED.value and previous_status != updated.status:
            self.alerts.send(
                f"order_rejected:{updated.order_ref}",
                f"Broker rejected {updated.purpose} order {updated.order_ref}",
                critical=True,
            )
        return updated

    def _recover_fills(self, positions: list[BrokerPosition]) -> None:
        option_positions = [
            position
            for position in positions
            if position.symbol == self.config.strategy.symbol and position.security_type == "OPT"
        ]
        for fill in self.broker.executions():
            if not fill.order_ref.startswith("AFV11-"):
                continue
            new_fill = self.store.record_fill(fill)
            order = self.store.get_order(order_ref=fill.order_ref)
            if order is None:
                matching = next((position for position in option_positions if position.con_id), None)
                if matching is None:
                    continue
                purpose = "entry" if _is_sell(fill.action) else "exit"
                order = OrderRecord(
                    intent_id=f"recovered:{fill.order_ref}",
                    order_ref=fill.order_ref,
                    purpose=purpose,
                    action="SELL" if purpose == "entry" else "BUY",
                    symbol=matching.symbol,
                    quantity=fill.quantity,
                    limit_price=fill.price,
                    status=OrderLifecycle.FILLED.value,
                    expiry=matching.expiry,
                    strike=matching.strike,
                    right=matching.right,
                    con_id=matching.con_id,
                    perm_id=fill.perm_id,
                    filled_quantity=fill.quantity,
                    average_fill_price=fill.price,
                    attempts=1,
                )
                self.store.upsert_order(order)
            else:
                order = self.store.update_order(
                    order.intent_id,
                    status=OrderLifecycle.FILLED.value,
                    perm_id=fill.perm_id,
                    filled_quantity=max(order.filled_quantity, fill.quantity),
                    average_fill_price=fill.price,
                )
            if order.purpose == "entry":
                self.store.create_strategy_position(order)
            elif order.purpose == "exit":
                local = self.store.open_strategy_position(self.config.strategy.symbol)
                fill_matches_local_exit = local is not None and (
                    str(local["exit_order_ref"]) == order.order_ref
                    or (
                        new_fill
                        and not str(local["exit_order_ref"])
                        and int(local["con_id"]) == order.con_id
                    )
                )
                if fill_matches_local_exit and local is not None:
                    self.store.update_strategy_position(
                        self.config.strategy.symbol,
                        PositionLifecycle.CLOSED.value,
                        exit_order_ref=order.order_ref,
                        position_id=str(local["position_id"]),
                    )
                    try:
                        filled_at = datetime.fromisoformat(fill.occurred_at)
                        self.store.mark_close_completed(self.clock.session_date(filled_at))
                    except ValueError:
                        self.store.mark_close_completed(self.clock.session_date())
            if new_fill:
                self._event("fill", **asdict(fill))
                self.alerts.send(
                    f"fill:{fill.execution_id}",
                    f"Filled {order.purpose} {fill.action} {fill.quantity} QQQ option @ {fill.price:.2f}",
                )

    def _mismatch_is_persistent(self, issues: list[str]) -> bool:
        signature = json.dumps(sorted(issues), ensure_ascii=False)
        previous = self.store.get_meta("reconciliation_mismatch", {})
        count = int(previous.get("count", 0)) + 1 if previous.get("signature") == signature else 1
        self.store.set_meta("reconciliation_mismatch", {"signature": signature, "count": count, "at": utc_now_iso()})
        return count >= 2

    def reconcile(self, *, halt_on_error: bool = True, accept_legacy: bool = False) -> ReconciliationResult:
        self._ensure_connected()
        account = self.broker.account_snapshot()
        fatal_issues = self._validate_account(account.account_id)
        if fatal_issues and (self.config.validate() or not self._account_is_authorized(account.account_id)):
            reason = "; ".join(fatal_issues)
            if halt_on_error:
                self.store.set_halt(reason, self.config.persistence.halt_file)
                self.alerts.send("fatal_account_or_config", reason, critical=True)
            result = ReconciliationResult(
                ok=False,
                account_id=account.account_id,
                stock_shares=0,
                short_calls=0,
                open_orders=0,
                issues=tuple(fatal_issues),
            )
            self._last_reconciliation = result
            self.store.set_meta("last_reconciliation", asdict(result))
            self._event("reconcile_fatal", **asdict(result))
            return result

        positions = self.broker.positions()
        self.store.replace_broker_positions(positions)
        stock_shares, short_call_positions = self._qqq_exposure(positions, self.config.strategy.symbol)
        short_calls = int(sum(abs(position.quantity) for position in short_call_positions))

        imported: list[str] = []
        broker_orders = self.broker.open_orders()
        for broker_order in broker_orders:
            if broker_order.symbol != self.config.strategy.symbol:
                continue
            if not broker_order.order_ref.startswith("AFV11-"):
                continue
            if self.store.get_order(order_ref=broker_order.order_ref) is None:
                imported.append(broker_order.order_ref)
            self._record_broker_order(broker_order)

        self._recover_fills(positions)
        local_position = self.store.open_strategy_position(self.config.strategy.symbol)
        active_broker_refs = {order.order_ref for order in broker_orders if order.order_ref.startswith("AFV11-")}
        issues = self._validate_account(account.account_id)

        all_option_positions = [position for position in positions if position.security_type == "OPT"]
        known_con_id = int(local_position["con_id"]) if local_position is not None else 0
        unknown_option_positions = [
            position
            for position in all_option_positions
            if not (
                known_con_id > 0
                and position.con_id == known_con_id
                and position.symbol == self.config.strategy.symbol
                and position.right.upper() == "C"
                and position.quantity == -self.config.strategy.contracts
                and position.multiplier == 100
            )
        ]
        if unknown_option_positions:
            issues.append(f"broker has {len(unknown_option_positions)} unknown option position(s)")

        unknown_orders = [
            order
            for order in broker_orders
            if order.symbol == self.config.strategy.symbol
            and order.security_type == "OPT"
            and not order.order_ref.startswith("AFV11-")
        ]
        if unknown_orders:
            issues.append("unknown active QQQ option order exists at broker")
        if stock_shares < self.config.strategy.required_shares:
            issues.append(
                f"QQQ collateral is {stock_shares}; at least {self.config.strategy.required_shares} shares are required"
            )
        if short_calls > self.config.strategy.contracts:
            issues.append(f"broker has {short_calls} short QQQ calls; pilot permits only one")
        if short_calls and local_position is None:
            issues.append("broker short QQQ call has no reconciled local strategy position")
        if local_position is not None and short_calls == 0:
            issues.append("local covered-call position is absent at broker; possible assignment or manual close")
        if local_position is not None and short_call_positions:
            broker_con_ids = {position.con_id for position in short_call_positions}
            if int(local_position["con_id"]) not in broker_con_ids:
                issues.append("local option contract does not match broker position")

        legacy_pending = self.store.get_meta("legacy_import_pending", {})
        if legacy_pending:
            exact_legacy_match = (
                local_position is not None
                and short_calls == 1
                and short_call_positions
                and int(local_position["con_id"]) in {position.con_id for position in short_call_positions}
            )
            if accept_legacy and exact_legacy_match:
                self.store.update_strategy_position(self.config.strategy.symbol, PositionLifecycle.OPEN.value)
                self.store.set_meta("legacy_import_pending", {})
            else:
                issues.append("legacy position import requires explicit --accept-legacy reconciliation")

        for local_order in self.store.active_orders():
            if local_order.order_ref not in active_broker_refs:
                matching_fill = any(fill.order_ref == local_order.order_ref for fill in self.broker.executions())
                if not matching_fill:
                    issues.append(f"local active order {local_order.order_ref} is absent at broker")

        immediate = (
            bool(self._validate_account(account.account_id))
            or stock_shares < self.config.strategy.required_shares
            or short_calls > self.config.strategy.contracts
            or bool(unknown_orders)
            or bool(unknown_option_positions)
            or (local_position is not None and short_calls == 0)
        )
        if issues:
            persistent = immediate or self._mismatch_is_persistent(issues)
            if halt_on_error and persistent:
                reason = "; ".join(issues)
                self.store.set_halt(reason, self.config.persistence.halt_file)
                self.alerts.send("reconciliation_halt", reason, critical=True)
        else:
            self.store.set_meta("reconciliation_mismatch", {"signature": "", "count": 0, "at": utc_now_iso()})

        result = ReconciliationResult(
            ok=not issues,
            account_id=account.account_id,
            stock_shares=stock_shares,
            short_calls=short_calls,
            open_orders=len(broker_orders),
            issues=tuple(issues),
            imported_order_refs=tuple(imported),
        )
        self._last_reconciliation = result
        self.store.set_meta("last_reconciliation", asdict(result))
        self._event("reconcile", **asdict(result))
        return result

    def doctor(self) -> dict[str, object]:
        checks: dict[str, object] = {"config": {"ok": not self.config.validate(), "issues": self.config.validate()}}
        try:
            self._ensure_connected()
            account = self.broker.account_snapshot()
            positions = self.broker.positions()
            shares, calls = self._qqq_exposure(positions, self.config.strategy.symbol)
            account_issues = self._validate_account(account.account_id)
            checks["gateway"] = {"ok": True, "host": self.config.broker.host, "port": self.config.broker.port}
            checks["account"] = {"ok": not account_issues, "account_id": account.account_id, "issues": account_issues}
            checks["collateral"] = {
                "ok": shares >= self.config.strategy.required_shares and len(calls) <= 1,
                "shares": shares,
                "short_calls": len(calls),
            }
            bars = self.broker.daily_bars(self.config.strategy.symbol, self.config.strategy.trend_period + 20)
            checks["daily_data"] = {"ok": len(bars) >= self.config.strategy.trend_period, "bars": len(bars)}
            spot, quotes = self.broker.covered_call_quotes(
                self.config.strategy.symbol,
                self.config.strategy.dte_min,
                self.config.strategy.dte_max,
            )
            selected = select_covered_call_quote(quotes, spot, self.config.strategy, self.config.execution)
            checks["option_data"] = {
                "ok": selected is not None,
                "spot": spot,
                "quotes": len(quotes),
                "selected": asdict(selected) if selected else None,
            }
        except Exception as exc:  # noqa: BLE001 - doctor reports broker failures instead of crashing
            checks["gateway"] = {"ok": False, "error": str(exc)}
        probe = getattr(self.alerts, "probe", None)
        if callable(probe):
            ok, detail = probe()
            checks["telegram"] = {"ok": ok, "detail": detail}
        else:
            checks["telegram"] = {"ok": False, "detail": "Telegram is not configured"}
        ok = all(bool(item.get("ok")) for item in checks.values() if isinstance(item, dict))
        return {"ok": ok, "checks": checks, "shadow_sessions": len(self.store.shadow_sessions())}

    def _health(self, *, connected: bool, status: str, detail: str = "") -> HealthSnapshot:
        result = self._last_reconciliation
        halted, reason = self.store.halt_state(self.config.persistence.halt_file)
        return HealthSnapshot(
            connected=connected,
            halted=halted,
            halt_reason=reason,
            account_id=result.account_id if result else "",
            stock_shares=result.stock_shares if result else 0,
            short_calls=result.short_calls if result else 0,
            active_orders=len(self.store.active_orders()),
            shadow_sessions=len(self.store.shadow_sessions()),
            last_heartbeat=utc_now_iso(),
            last_cycle_status=status,
            details={"detail": detail},
        )

    def _sync_working_orders(self, now: datetime) -> None:
        broker_by_ref = {order.order_ref: order for order in self.broker.open_orders()}
        for local in self.store.active_orders():
            broker_order = broker_by_ref.get(local.order_ref)
            if broker_order is None:
                continue
            current = self._record_broker_order(broker_order)
            if current.status == OrderLifecycle.FILLED.value:
                continue
            marker = self.store.get_meta(f"order_action:{current.order_ref}", {})
            last_action_at = str(marker.get("at", current.created_at))
            age = datetime.now(timezone.utc) - datetime.fromisoformat(last_action_at)
            if age.total_seconds() < self.config.execution.reprice_interval_seconds:
                continue
            max_attempts = (
                self.config.execution.max_entry_attempts
                if current.purpose == "entry"
                else self.config.execution.max_exit_attempts_per_cycle
            )
            if current.attempts >= max_attempts:
                self.broker.cancel(current.order_ref)
                self.store.update_order(current.intent_id, status=OrderLifecycle.CANCELLED.value)
                self._event("order_cancelled", order_ref=current.order_ref, purpose=current.purpose)
                self.alerts.send(
                    f"order_cancelled:{current.order_ref}",
                    f"{current.purpose} order {current.order_ref} cancelled after {current.attempts} attempts",
                    critical=current.purpose == "exit",
                )
                if current.purpose == "exit":
                    retry = self.store.get_meta("last_exit_retry", {})
                    self.store.set_meta(
                        "last_exit_retry",
                        {
                            "at": now.astimezone(timezone.utc).isoformat(),
                            "sequence": int(retry.get("sequence", 0)) + 1,
                        },
                    )
                continue
            quote = self._fresh_option_quote(
                current.symbol,
                current.expiry,
                current.strike,
                current.right,
                current.con_id,
                now,
            )
            boundary = quote.bid if _is_sell(current.action) else quote.ask
            new_price = next_limit_price(
                current.limit_price,
                current.action,
                self.config.execution.tick_size,
                boundary,
            )
            updated = self.broker.modify_limit(current.order_ref, new_price)
            self.store.update_order(
                current.intent_id,
                status=updated.status,
                limit_price=new_price,
                attempts=current.attempts + 1,
                broker_order_id=updated.broker_order_id,
                perm_id=updated.perm_id,
            )
            self.store.set_meta(
                f"order_action:{current.order_ref}",
                {"at": now.astimezone(timezone.utc).isoformat(), "attempt": current.attempts + 1},
            )
            self._event("order_repriced", order_ref=current.order_ref, price=new_price, attempt=current.attempts + 1)

    def _cancel_entries_for_halt(self) -> None:
        for order in self.store.active_orders("entry"):
            try:
                self.broker.cancel(order.order_ref)
            except KeyError:
                pass
            self.store.update_order(order.intent_id, status=OrderLifecycle.CANCELLED.value)
            self._event("halt_cancel_entry", order_ref=order.order_ref)
            self.alerts.send(
                f"halt_cancel_entry:{order.order_ref}",
                f"Cancelled pending entry {order.order_ref} because HALT is active",
                critical=True,
            )

    def _known_position_can_exit(self, result: ReconciliationResult) -> bool:
        local = self.store.open_strategy_position(self.config.strategy.symbol)
        return (
            local is not None
            and result.account_id == self.config.expected_account_id
            and result.short_calls == 1
            and int(local["con_id"]) > 0
        )

    def _submit(self, intent: TradeIntent) -> OrderRecord:
        existing = self.store.get_order(intent_id=intent.intent_id)
        if existing and existing.status in {
            OrderLifecycle.SUBMITTED.value,
            OrderLifecycle.PARTIALLY_FILLED.value,
            OrderLifecycle.FILLED.value,
        }:
            return existing
        created = OrderRecord(
            intent_id=intent.intent_id,
            order_ref=intent.order_ref,
            purpose=intent.purpose,
            action=intent.action,
            symbol=intent.symbol,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            expiry=intent.expiry,
            strike=intent.strike,
            right=intent.right,
            con_id=intent.con_id,
            attempts=(existing.attempts + 1) if existing else 1,
            created_at=existing.created_at if existing else utc_now_iso(),
        )
        self.store.upsert_order(created)
        broker_order = self.broker.submit_limit(intent, self.config.execution.tif)
        updated = self.store.update_order(
            created.intent_id,
            status=broker_order.status,
            broker_order_id=broker_order.broker_order_id,
            perm_id=broker_order.perm_id,
            filled_quantity=broker_order.filled_quantity,
            limit_price=broker_order.limit_price,
            attempts=created.attempts,
        )
        self.store.set_meta(
            f"order_action:{created.order_ref}",
            {"at": utc_now_iso(), "attempt": created.attempts},
        )
        self._event("order_submitted", **asdict(updated))
        self.alerts.send(
            f"order_submitted:{updated.order_ref}",
            f"{updated.purpose} {updated.action} {updated.quantity} QQQ call @ {updated.limit_price:.2f}",
        )
        if updated.status == OrderLifecycle.REJECTED.value:
            self.alerts.send(
                f"order_rejected:{updated.order_ref}",
                f"Broker rejected {updated.purpose} order {updated.order_ref}",
                critical=True,
            )
        return updated

    def _fresh_option_quote(
        self,
        symbol: str,
        expiry: str,
        strike: float,
        right: str,
        con_id: int,
        now: datetime,
    ) -> OptionMarketQuote:
        quote = self.broker.option_quote(
            symbol,
            expiry,
            strike,
            right,
            con_id,
        )
        if not all(math.isfinite(value) for value in (quote.bid, quote.ask, quote.delta)):
            raise RuntimeError("exit quote contains non-finite values")
        if quote.bid <= 0 or quote.ask <= 0 or quote.ask < quote.bid:
            raise RuntimeError("exit quote has invalid bid/ask")
        if quote.delayed and not self.config.execution.allow_delayed_data:
            raise RuntimeError("exit quote is delayed")
        if quote_age_seconds(quote, now) > self.config.execution.quote_max_age_seconds:
            raise RuntimeError("exit quote is stale")
        return quote

    def _fresh_exit_quote(self, local_position: dict[str, Any], now: datetime) -> OptionMarketQuote:
        return self._fresh_option_quote(
            str(local_position["symbol"]),
            str(local_position["expiry"]),
            float(local_position["strike"]),
            str(local_position["right"]),
            int(local_position["con_id"]),
            now,
        )

    def _manage_position(self, now: datetime) -> None:
        local = self.store.open_strategy_position(self.config.strategy.symbol)
        if local is None or self.store.active_orders("exit"):
            return
        if not self.clock.in_management_window(now):
            return
        retry = self.store.get_meta("last_exit_retry", {})
        if retry.get("at"):
            last = datetime.fromisoformat(str(retry["at"]))
            if now.astimezone(timezone.utc) - last < time_delta(self.config.schedule.exit_retry_seconds):
                return
        quote = self._fresh_exit_quote(local, now)
        reason = exit_reason(
            float(local["entry_credit"]),
            quote.ask,
            str(local["expiry"]),
            self.config.strategy.force_exit_dte,
            self.clock.eastern(now).date(),
        )
        if reason is None:
            return
        intent = make_intent(
            purpose="exit",
            action="BUY",
            quote=quote,
            quantity=int(local["quantity"]),
            limit_price=quote.mid,
            session_date=self.clock.session_date(now),
            reason=(
                f"{reason}:retry:{int(retry.get('sequence', 0))}"
                if int(retry.get("sequence", 0)) > 0
                else reason
            ),
        )
        self.store.update_strategy_position(
            self.config.strategy.symbol,
            PositionLifecycle.EXIT_PENDING.value,
            exit_order_ref=intent.order_ref,
        )
        self._submit(intent)

    def _attempt_entry(self, now: datetime, result: ReconciliationResult) -> None:
        session_date = self.clock.session_date(now)
        if not self.clock.in_entry_window(now):
            return
        if self.store.close_completed(session_date) or self.store.entry_attempted(session_date):
            return
        if result.short_calls or self.store.open_strategy_position(self.config.strategy.symbol):
            return
        if self.store.active_orders("entry"):
            return
        bars = self.broker.daily_bars(self.config.strategy.symbol, self.config.strategy.trend_period + 20)
        diagnostics = completed_bar_diagnostics(bars, self.config.strategy.trend_period)
        bullish = bool(diagnostics["bullish"])
        self._event("entry_signal", session_date=session_date, **diagnostics)
        if not bullish:
            if self.config.shadow_mode:
                self.store.mark_entry_attempt(session_date, "shadow:no_bullish_signal")
                count = self.store.mark_shadow_session(session_date)
                self.alerts.send(
                    f"shadow:{session_date}",
                    f"Shadow decision: no entry because QQQ is below EMA200 ({count}/"
                    f"{self.config.shadow_sessions_required})",
                )
            return
        spot, quotes = self.broker.covered_call_quotes(
            self.config.strategy.symbol,
            self.config.strategy.dte_min,
            self.config.strategy.dte_max,
        )
        selected = select_covered_call_quote(
            quotes,
            spot,
            self.config.strategy,
            self.config.execution,
            as_of=self.clock.eastern(now).date(),
            now=now,
        )
        if selected is None:
            self.alerts.send("no_safe_contract", "No safe QQQ covered-call contract passed quote filters")
            return
        intent = make_intent(
            purpose="entry",
            action="SELL",
            quote=selected,
            quantity=self.config.strategy.contracts,
            limit_price=selected.mid,
            session_date=session_date,
            reason="qqq_close_above_ema200",
        )
        self.store.mark_entry_attempt(session_date, intent.intent_id)
        if self.config.shadow_mode:
            count = self.store.mark_shadow_session(session_date)
            self._event("shadow_intent", intent=asdict(intent), completed_shadow_sessions=count)
            self.alerts.send(
                f"shadow:{session_date}",
                f"Shadow entry: SELL 1 QQQ {selected.expiry} {selected.strike:.0f}C @ {selected.mid:.2f} ({count}/"
                f"{self.config.shadow_sessions_required})",
            )
            return
        if not self.config.trading_enabled:
            self._event("entry_blocked", reason="trading_enabled_false", intent=asdict(intent))
            return
        if len(self.store.shadow_sessions()) < self.config.shadow_sessions_required:
            self.store.set_halt("shadow-session gate has not completed", self.config.persistence.halt_file)
            self.alerts.send("shadow_gate", "Trading blocked: five shadow sessions have not completed", critical=True)
            return
        self._submit(intent)

    def _operational_notices(self, now: datetime) -> None:
        local = self.clock.eastern(now)
        session_date = local.date().isoformat()
        if local.weekday() == 4 and (local.hour, local.minute) >= (15, 30):
            self.alerts.send(f"weekly_reauth:{session_date}", "Weekend IB Gateway reauthentication will be required")
        if (local.hour, local.minute) >= (16, 5) and not self.store.get_meta(f"daily_summary:{session_date}", False):
            status = self.store.status_dict(self.config.persistence.halt_file)
            self.alerts.send(f"daily_summary:{session_date}", f"Daily status: {json.dumps(status, ensure_ascii=False)}")
            self.store.set_meta(f"daily_summary:{session_date}", True)

    def run_cycle(self, now: datetime | None = None) -> ReconciliationResult | None:
        now = now or datetime.now(timezone.utc)
        started = utc_now_iso()
        try:
            self._ensure_connected()
            result = self.reconcile()
            safe_runtime = not self.config.validate() and self._account_is_authorized(result.account_id)
            if not safe_runtime:
                detail = "; ".join(result.issues) or "unsafe runtime configuration"
                self.store.record_cycle(started, "fatal", detail)
                self.store.write_heartbeat(self._health(connected=False, status="fatal", detail=detail))
                self.alerts.send("fatal_runtime_exit", f"Daemon exiting without broker mutation: {detail}", critical=True)
                self.broker.disconnect()
                return result
            halted, _reason = self.store.halt_state(self.config.persistence.halt_file)
            if halted:
                self._cancel_entries_for_halt()
            self._sync_working_orders(now)
            if result.ok or self._known_position_can_exit(result):
                self._manage_position(now)
            if result.ok and not halted:
                self._attempt_entry(now, result)
            if result.ok and self.clock.is_session(now):
                self.store.mark_monitor_session(self.clock.session_date(now))
            self._operational_notices(now)
            status = "ok" if result.ok else "reconciliation_warning"
            self.store.record_cycle(started, status, "; ".join(result.issues))
            self.store.write_heartbeat(self._health(connected=True, status=status))
            return result
        except Exception as exc:
            logger.exception("unattended cycle failed")
            self.store.record_cycle(started, "error", str(exc))
            self.store.write_heartbeat(self._health(connected=self.broker.is_connected(), status="error", detail=str(exc)))
            self.alerts.send("cycle_error", f"Unattended cycle failed: {exc}", critical=True)
            if not self.broker.is_connected():
                self.store.set_meta("broker_connection", {"status": "disconnected", "at": utc_now_iso()})
                self.alerts.send("broker_disconnected", "IB Gateway connection is down", critical=True)
            return None

    def run_daemon(self) -> None:
        with ProcessLock(self.config.persistence.lock_file):
            self.alerts.send("daemon_started", "Unattended paper daemon started")
            try:
                while True:
                    result = self.run_cycle()
                    if result is not None and (
                        self.config.validate() or not self._account_is_authorized(result.account_id)
                    ):
                        break
                    if result is None and self.broker.is_connected():
                        self.broker.disconnect()
                    time.sleep(self.config.schedule.monitor_interval_seconds)
            except KeyboardInterrupt:
                pass
            finally:
                self.alerts.send("daemon_stopped", "Unattended paper daemon stopped")
                self.broker.disconnect()


def time_delta(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)
