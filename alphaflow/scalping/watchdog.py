"""Independent heartbeat watchdog for the SPY scalping Windows task."""

from __future__ import annotations

from datetime import datetime, timezone

from alphaflow.scalping.alerts import ScalpAlertSink
from alphaflow.scalping.config import ScalpConfig
from alphaflow.scalping.store import ScalpingStore


def check_scalp_heartbeat(
    config: ScalpConfig,
    store: ScalpingStore,
    alerts: ScalpAlertSink,
) -> tuple[bool, str]:
    stamp = store.get_metadata("last_heartbeat")
    if not stamp:
        message = "No AlphaFlow SPY scalper heartbeat has been recorded"
        alerts.send("watchdog_missing", message, critical=True)
        return False, message
    try:
        then = datetime.fromisoformat(stamp)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
    except ValueError:
        message = f"Invalid scalper heartbeat timestamp: {stamp}"
        alerts.send("watchdog_invalid", message, critical=True)
        return False, message
    age = (datetime.now(timezone.utc) - then.astimezone(timezone.utc)).total_seconds()
    if age > config.alerts.heartbeat_stale_seconds:
        message = f"AlphaFlow SPY scalper heartbeat is stale ({age:.0f}s)"
        alerts.send("watchdog_stale", message, critical=True)
        return False, message
    return True, f"scalper heartbeat healthy ({age:.0f}s)"
