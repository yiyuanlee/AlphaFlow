"""Local audit journal and Telegram alert delivery."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from alphaflow.core.persistence.journal import append_event

from .config import AlertConfig
from .store import UnattendedStore

logger = logging.getLogger(__name__)


class AlertSink(Protocol):
    def send(self, key: str, message: str, *, critical: bool = False) -> bool: ...


class NullAlertSink:
    def __init__(self, journal: Path):
        self.journal = journal

    def send(self, key: str, message: str, *, critical: bool = False) -> bool:
        append_event(self.journal, "alert", key=key, message=message, critical=critical, delivered=False)
        return False


class TelegramAlertSink:
    def __init__(self, config: AlertConfig, store: UnattendedStore, journal: Path):
        self.config = config
        self.store = store
        self.journal = journal
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
            payload = self._request("getMe")
            return bool(payload.get("ok")), "ok" if payload.get("ok") else str(payload)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return False, str(exc)

    def send(self, key: str, message: str, *, critical: bool = False) -> bool:
        append_event(self.journal, "alert", key=key, message=message, critical=critical, delivered=False)
        if not self.configured:
            logger.error("Telegram not configured: %s", message)
            return False
        if not self.store.should_send_alert(key, self.config.dedupe_minutes, message):
            return False
        prefix = "🚨 AlphaFlow V11" if critical else "AlphaFlow V11"
        try:
            response = self._request("sendMessage", {"chat_id": self.chat_id, "text": f"{prefix}\n{message}"})
            delivered = bool(response.get("ok"))
            append_event(self.journal, "alert_delivery", key=key, delivered=delivered)
            return delivered
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            logger.exception("Telegram delivery failed")
            append_event(self.journal, "alert_delivery", key=key, delivered=False, error=str(exc))
            return False


def build_alert_sink(config: AlertConfig, store: UnattendedStore, journal: Path) -> AlertSink:
    sink = TelegramAlertSink(config, store, journal)
    return sink if sink.configured else NullAlertSink(journal)
