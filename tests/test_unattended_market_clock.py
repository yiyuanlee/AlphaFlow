from datetime import datetime, timezone

from alphaflow.options.unattended.config import ScheduleConfig
from alphaflow.options.unattended.market_clock import MarketClock


def test_entry_window_handles_dst_and_standard_time():
    clock = MarketClock(ScheduleConfig())
    assert clock.in_entry_window(datetime(2026, 8, 19, 14, 15, tzinfo=timezone.utc))
    assert clock.in_entry_window(datetime(2026, 1, 15, 15, 15, tzinfo=timezone.utc))


def test_nyse_holiday_is_not_a_session():
    clock = MarketClock(ScheduleConfig())
    assert not clock.is_session(datetime(2026, 12, 25, 15, 15, tzinfo=timezone.utc))
