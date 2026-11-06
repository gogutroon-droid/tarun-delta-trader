import argparse
import logging
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from config.default_settings import BotConfig
from src.live.live_trader import LiveTrader


def setup_logging(log_level: str = "INFO"):
    os.makedirs("logs", exist_ok=True)
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("logs/bot.log", encoding="utf-8"),
        ],
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Delta Trader Execution Runner")
    parser.add_argument("--mode", type=str, choices=["PAPER", "TESTNET"], help="Execution mode (PAPER or TESTNET)")
    parser.add_argument("--symbol", type=str, default="BTCUSD", help="Trading symbol (e.g. BTCUSD)")
    parser.add_argument("--currency", type=str, choices=["INR", "USDT"], help="Account currency (INR or USDT)")
    parser.add_argument("--capital", type=float, help="Starting account capital (in selected currency)")
    parser.add_argument("--risk", type=float, help="Risk percentage per trade (e.g. 0.03 for 3%)")
    parser.add_argument("--enable-trading", action="store_true", help="Enable testnet order execution (TRADING_ENABLED=true)")
    parser.add_argument("--config", type=str, default="config/config.json", help="Path to config JSON file")
    parser.add_argument("--once", action="store_true", help="Run a single surveillance check and exit")
    return parser.parse_args()


def main():
    setup_logging()
    args = parse_args()

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(__file__), config_path)

    config = BotConfig.from_json(config_path)

    if args.mode:
        config.mode = args.mode.upper()
    if args.symbol:
        config.symbol = args.symbol.upper()
    if args.currency:
        config.currency = args.currency.upper()
    if args.capital:
        if config.currency == "INR":
            config.account.starting_capital_inr = args.capital
        else:
            config.account.starting_capital_usdt = args.capital
    if args.risk:
        config.account.risk_per_trade_pct = args.risk
    if args.enable_trading:
        config.api.trading_enabled = True

    trader = LiveTrader(config=config)

    if args.once:
        trader.initialize()
        print("\n[*] Executing single live market surveillance check on Delta Exchange...")
        trader.run_tick()
        print("[*] Single tick check completed.")
    else:
        trader.start()


if __name__ == "__main__":
    main()
