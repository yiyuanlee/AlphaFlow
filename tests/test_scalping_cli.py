from alphaflow.cli import build_parser
from alphaflow.config import load_config
from alphaflow.scalping.config import scalp_config_from_yaml


def test_scalping_cli_surface_and_safe_profile_defaults():
    parser = build_parser()
    for command in ("download", "backtest", "doctor", "run", "status", "reconcile", "halt", "resume", "watchdog"):
        argv = ["scalp", command, "--profile", "paper_spy_orb"]
        if command == "halt":
            argv.extend(["--reason", "test"])
        if command == "resume":
            argv.extend(["--confirm-account", "DU123"])
        assert parser.parse_args(argv).handler is not None
    config = scalp_config_from_yaml(load_config(profile="paper_spy_orb"))
    assert config.broker.port == 4004
    assert config.broker.client_id == 4
    assert config.shadow_mode
    assert not config.trading_enabled
    assert config.strategy.symbol == "SPY"
