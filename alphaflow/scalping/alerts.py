"""Deduplicated local audit and Telegram notifications for the scalper."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Protocol

from alphaflow.scalping.config import ScalpAlertConfig
from alphaflow.scalping.store import ScalpingStore

logger = logging.getLogger(__name__)


class ScalpAlertSink(Protocol):
    def probe(self) -> tuple[bool, str]: ...

    def send(self, key: str, message: str, *, critical: bool = False) -> bool: ...


class NullScalpAlertSink:
    def __init__(self, store: ScalpingStore) -> None:
        self.store = store

    def probe(self) -> tuple[bool, str]:
        return False, "Telegram environment variables are missing"

    def send(self, key: str, message: str, *, critical: bool = False) -> bool:
        self.store.journal_event("alert", {"key": key, "message": message, "critical": critical, "delivered": False})
        return False


class TelegramScalpAlertSink:
    def __init__(self, config: ScalpAlertConfig, store: ScalpingStore) -> None:
        self.config = config
        self.store = store
        self.token = os.environ.get(config.telegram_token_env, "").strip()
        self.chat_id = os.environ.get(config.telegram_chat_id_env, "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def _request(self, method: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def probe(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "Telegram environment variables are missing"
        try:
            response = self._request("getMe")
            return bool(response.get("ok")), "ok" if response.get("ok") else str(response)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return False, str(exc)

    def send(self, key: str, message: str, *, critical: bool = False) -> bool:
        self.store.journal_event("alert", {"key": key, "message": message, "critical": critical, "delivered": False})
        if not self.configured:
            logger.error("Telegram not configured: %s", message)
            return False
        if not self.store.alert_due(key, message, self.config.dedupe_minutes * 60):
            return False
        prefix = "🚨 AlphaFlow SPY Scalper" if critical else "AlphaFlow SPY Scalper"
        try:
            response = self._request("sendMessage", {"chat_id": self.chat_id, "text": f"{prefix}\n{message}"})
            delivered = bool(response.get("ok"))
            self.store.journal_event("alert_delivery", {"key": key, "delivered": delivered})
            if not delivered:
                self.store.release_alert(key)
            return delivered
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            logger.exception("Telegram delivery failed")
            self.store.release_alert(key)
            self.store.journal_event("alert_delivery", {"key": key, "delivered": False, "error": str(exc)})
            return False


def build_scalp_alert_sink(config: ScalpAlertConfig, store: ScalpingStore) -> ScalpAlertSink:
    sink = TelegramScalpAlertSink(config, store)
    return sink if sink.configured else NullScalpAlertSink(store)
