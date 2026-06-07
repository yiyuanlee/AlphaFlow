"""Statistics for options paper journal."""

from __future__ import annotations

from collections import Counter
from typing import Any

from alphaflow.options.journal import load_options_events


def analyze_options_journal(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    events = events if events is not None else load_options_events()
    opens = [e for e in events if e.get('event') == 'open']
    closes = [e for e in events if e.get('event') == 'close']
    intents = Counter(e.get('intent', 'unknown') for e in opens)
    realized = sum(float(e.get('pnl', 0)) for e in closes)
    return {
        'total_events': len(events),
        'opens': len(opens),
        'closes': len(closes),
        'open_by_intent': dict(intents),
        'realized_pnl': realized,
    }


def format_options_stats(stats: dict[str, Any]) -> str:
    lines = [
        '=== Options Paper Stats ===',
        f"Events: {stats['total_events']}",
        f"Opens: {stats['opens']} | Closes: {stats['closes']}",
        f"Realized PnL: ${stats['realized_pnl']:,.2f}",
    ]
    if stats['open_by_intent']:
        lines.append('Opens by strategy:')
        for k, v in sorted(stats['open_by_intent'].items()):
            lines.append(f'  {k}: {v}')
    return '\n'.join(lines)
