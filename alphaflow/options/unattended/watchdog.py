"""Independent heartbeat watchdog for Windows Task Scheduler."""

from __future__ import annotations

from datetime import datetime, timezone

from .alerts import AlertSink
from .config import UnattendedPaperConfig
from .store import UnattendedStore


def check_heartbeat(config: UnattendedPaperConfig, store: UnattendedStore, alerts: AlertSink) -> tuple[bool, str]:
    heartbeat = store.get_meta("heartbeat", {})
    stamp = str(heartbeat.get("last_heartbeat", ""))
    if not stamp:
        message = "No AlphaFlow V11 heartbeat has been recorded"
        alerts.send("watchdog_missing", message, critical=True)
        return False, message
    try:
        then = datetime.fromisoformat(stamp)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
    except ValueError:
        message = f"Invalid heartbeat timestamp: {stamp}"
        alerts.send("watchdog_invalid", message, critical=True)
        return False, message
    age = (datetime.now(timezone.utc) - then.astimezone(timezone.utc)).total_seconds()
    if age > config.alerts.heartbeat_stale_seconds:
        message = f"AlphaFlow V11 heartbeat is stale ({age:.0f}s)"
        alerts.send("watchdog_stale", message, critical=True)
        return False, message
    return True, f"heartbeat healthy ({age:.0f}s)"
