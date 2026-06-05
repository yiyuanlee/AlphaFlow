"""Statistics for hot-stock paper journal and replay results."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from alphaflow.hot_journal import load_hot_events


def _count_values(values) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for v in values:
        counts[str(v)] += 1
    return dict(counts)


def analyze_paper_journal(log_file=None) -> dict[str, Any]:
    events = load_hot_events(log_file)
    if not events:
        return {'events': 0, 'message': 'No paper trades logged yet'}

    entries = [e for e in events if e.get('event') == 'entry']
    exits = [e for e in events if e.get('event') == 'exit']
    skips = [e for e in events if e.get('event') == 'signal_skip']

    paired: list[dict[str, Any]] = []
    open_entries: dict[str, dict] = {}
    for e in events:
        if e.get('event') == 'entry':
            sym = e.get('symbol')
            if sym:
                open_entries[sym] = e
        elif e.get('event') == 'exit':
            sym = e.get('symbol')
            ent = open_entries.pop(sym, None)
            if ent and sym:
                entry_px = float(ent.get('price', 0))
                exit_px = float(e.get('price', 0))
                pnl_pct = (exit_px / entry_px - 1) * 100 if entry_px else 0.0
                paired.append({
                    'symbol': sym,
                    'entry_ts': ent.get('ts'),
                    'exit_ts': e.get('ts'),
                    'entry_price': entry_px,
                    'exit_price': exit_px,
                    'pnl_pct': pnl_pct,
                    'exit_reason': e.get('reason'),
                    'hold_days': e.get('hold_days'),
                })

    wins = [p for p in paired if p['pnl_pct'] > 0]
    losses = [p for p in paired if p['pnl_pct'] <= 0]
    gross_win = sum(p['pnl_pct'] for p in wins)
    gross_loss = abs(sum(p['pnl_pct'] for p in losses)) or 1e-9

    skip_reasons: dict[str, int] = defaultdict(int)
    for s in skips:
        skip_reasons[s.get('reason', 'unknown')] += 1

    return {
        'events': len(events),
        'entries': len(entries),
        'exits': len(exits),
        'paired_trades': len(paired),
        'open_positions': list(open_entries.keys()),
        'win_rate_pct': len(wins) / len(paired) * 100 if paired else 0.0,
        'avg_pnl_pct': sum(p['pnl_pct'] for p in paired) / len(paired) if paired else 0.0,
        'profit_factor': gross_win / gross_loss if paired else 0.0,
        'exit_reasons': _count_values(p.get('exit_reason', 'unknown') for p in paired),
        'skip_reasons': dict(skip_reasons),
        'trades': paired,
    }


def format_paper_stats(stats: dict[str, Any]) -> str:
    if stats.get('events', 0) == 0:
        return stats.get('message', 'No data')

    lines = [
        '=' * 60,
        '  Hot-Stock Paper Trading Stats',
        '=' * 60,
        f"  Events: {stats['events']}  Entries: {stats['entries']}  Exits: {stats['exits']}",
        f"  Paired trades: {stats['paired_trades']}",
        f"  Win rate: {stats['win_rate_pct']:.1f}%",
        f"  Avg PnL %: {stats['avg_pnl_pct']:+.2f}%",
        f"  Profit factor (pct): {stats['profit_factor']:.2f}",
    ]
    if stats.get('open_positions'):
        lines.append(f"  Open: {', '.join(stats['open_positions'])}")
    if stats.get('skip_reasons'):
        lines.append('  Signal skips:')
        for k, v in sorted(stats['skip_reasons'].items(), key=lambda x: -x[1]):
            lines.append(f'    {k}: {v}')
    if stats.get('trades'):
        lines.append('  Recent trades:')
        for t in stats['trades'][-5:]:
            lines.append(
                f"    {t['symbol']} {t['pnl_pct']:+.2f}% ({t.get('exit_reason')})"
            )
    return '\n'.join(lines)


def format_replay_stats(summary: dict[str, Any]) -> str:
    lines = [
        '=' * 60,
        '  Hot-Stock Daily Replay (Scanner Proxy)',
        '=' * 60,
        f"  Trades: {summary.get('trades', 0)}",
        f"  Total return: {summary.get('total_return_pct', 0):+.2f}%",
        f"  Final equity: ${summary.get('final_equity', 0):,.0f}",
    ]
    if summary.get('trades', 0) > 0:
        lines.extend([
            f"  Win rate: {summary.get('win_rate_pct', 0):.1f}%",
            f"  Profit factor: {summary.get('profit_factor', 0):.2f}",
            f"  Avg trade: {summary.get('avg_pnl_pct', 0):+.2f}%",
            f"  Max drawdown: {summary.get('max_drawdown_pct', 0):.2f}%",
        ])
    if summary.get('exit_reasons'):
        lines.append('  Exit reasons: ' + str(summary['exit_reasons']))
    if summary.get('signal_stats'):
        lines.append('  Signal stats:')
        for k, v in sorted(summary['signal_stats'].items(), key=lambda x: -x[1]):
            lines.append(f'    {k}: {v}')
    return '\n'.join(lines)
