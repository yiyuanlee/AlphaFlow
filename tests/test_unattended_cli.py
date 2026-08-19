from __future__ import annotations

import argparse

import pytest

from alphaflow import cli


def test_v11_profile_is_accepted_at_each_cli_level() -> None:
    parser = cli.build_parser()

    for argv in (
        ["--profile", "paper_qqq_cc", "options", "status", "--json"],
        ["options", "--profile", "paper_qqq_cc", "status", "--json"],
        ["options", "status", "--profile", "paper_qqq_cc", "--json"],
    ):
        args = parser.parse_args(argv)
        assert args.profile == "paper_qqq_cc"
        assert args.handler is cli._cmd_options_status


def test_legacy_options_entry_is_always_forced_to_dry_run(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(relative_path: str, argv: list[str]) -> int:
        captured["path"] = relative_path
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(cli, "_run_legacy_script", fake_run)

    result = cli._cmd_options_run(
        argparse.Namespace(profile=None, loop=False, live=True, daemon=False, dry_run=False)
    )

    assert result == 0
    assert captured == {
        "path": "scripts/live/ibkr_options.py",
        "argv": ["--live", "--dry-run"],
    }


def test_v11_rejects_any_profile_alias() -> None:
    with pytest.raises(ValueError, match="paper_qqq_cc"):
        cli._v11_context(argparse.Namespace(profile="something_else", config=None))
