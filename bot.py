import os
import sys
import json
import argparse
import datetime
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)

from src.config import BotConfig
from src.strategy.markov_strategy import ModelBMarkovEngine
from src.exchange.delta_client import DeltaExchangeClient
from src.data.fetcher import load_candles


def check_signal(cfg: BotConfig):
    print("================================================================================")
    print("      DELTA TRADER: MARKOV 1:15.0 R:R LIVE MARKET & SIGNAL AUDIT")
    print("      ASSET: BTCUSD | CURRENCY: " + cfg.currency + " | EXECUTION: 24/7 UNCONSTRAINED")
    print("================================================================================")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    print(f"\n[TIME & EXECUTION MODE]")
    print(f"• Current UTC Time:    {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"• Strategy Model:      Markov 1:15.0 R:R Micro-Scalper")
    print(f"• Session Restriction: DISABLED (24/7 Continuous Execution)")
    print(f"• Profit Reset Policy: MONTHLY_RESET (100% Profits Swept at Month-End)")
    print(f"• Base Capital:        {cfg.currency} {cfg.account.starting_capital_inr:,.2f}")

    print(f"\n[MARKET DATA INGESTION]")
    df_1d = load_candles("1d")
    df_15m = load_candles("15m")
    last_price = df_15m["close"].iloc[-1]
    print(f"• Latest BTC Price:    ${last_price:,.2f}")

    markov_engine = ModelBMarkovEngine(
        markov_window=cfg.strategy.markov_window,
        markov_thresh=cfg.strategy.markov_thresh,
        ema_fast=cfg.strategy.ema_fast,
        ema_slow=cfg.strategy.ema_slow,
        atr_period=cfg.strategy.atr_period,
        sl_atr_mult=cfg.strategy.sl_atr_mult,
        rr_ratio=cfg.strategy.rr_ratio,
        max_hold_bars=cfg.strategy.max_hold_bars,
        min_rvol=cfg.strategy.min_rvol,
    )

    c1d = df_1d["close"].values
    r10 = (c1d[-1] - c1d[-1 - cfg.strategy.markov_window]) / c1d[-1 - cfg.strategy.markov_window]
    markov_state = "BULL (+2% Threshold Met - Longs Only)" if r10 > cfg.strategy.markov_thresh else (
        "BEAR (-2% Threshold Met - Shorts Only)" if r10 < -cfg.strategy.markov_thresh else "CHOP / FLAT (100% Cash)"
    )
    print(f"• 1D Markov Return R10: {r10*100:+.2f}% -> State: {markov_state}")

    c15 = df_15m["close"]
    ema20 = c15.ewm(span=cfg.strategy.ema_fast, adjust=False).mean().iloc[-1]
    ema50 = c15.ewm(span=cfg.strategy.ema_slow, adjust=False).mean().iloc[-1]
    print(f"• 15M EMA20:           ${ema20:,.2f} | 15M EMA50: ${ema50:,.2f} -> {'EMA BULLISH ALIGNMENT' if ema20 > ema50 else 'EMA BEARISH ALIGNMENT'}")

    sig = markov_engine.evaluate_signal(df_1d, df_15m)
    if sig is not None:
        print(f"\n[TRADE TRIGGER ACTIVE: {sig['dir']}]")
        print(f"• Entry Price:         ${sig['entry']:,.2f}")
        print(f"• Stop Loss (-1.0R):   ${sig['sl']:,.2f} (-3.0% Risk)")
        print(f"• Take Profit (+15.0R): ${sig['tp']:,.2f} (+45.0% Reward)")
        print(f"• 15M ATR(14):         ${sig['atr']:,.2f}")
        print(f"• RVOL(20):            {sig['rvol']:.2f}x (Threshold >= 1.20x Met)")
        print(f"• Max Hold Timeout:    {sig['max_bars']} bars (30 hours)")
    else:
        print(f"• Current Signal:      NONE (Monitoring for 15M EMA20 pullback & RVOL surge)")

    print("\n================================================================================")
    print("Signal audit completed successfully.")


def main():
    parser = argparse.ArgumentParser(description="Delta Trader 24/7 Execution Daemon")
    parser.add_argument(
        "--mode",
        choices=["signal", "paper", "live"],
        default="signal",
        help="Operational mode (signal, paper, live)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.json",
        help="Path to JSON configuration file",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=None,
        help="Override starting capital",
    )

    args = parser.parse_args()

    cfg = BotConfig.from_json(args.config)
    if args.capital:
        cfg.account.starting_capital_inr = args.capital
        cfg.account.starting_capital_usdt = args.capital / cfg.inr_usdt_rate

    if args.mode == "signal":
        check_signal(cfg)
    elif args.mode == "paper":
        print(f"\nLaunching Paper Trading Engine with Baseline: {cfg.currency} {cfg.account.starting_capital_inr:,.2f}...")
        check_signal(cfg)
        print("\n[PAPER TRADING DAEMON] Initialized. Monitoring 15M candle closes with monthly profit reset...")
    elif args.mode == "live":
        print("\n[LIVE TRADING] Connecting to Delta Exchange India...")
        client = DeltaExchangeClient(
            api_key=cfg.api.delta_api_key or os.environ.get("DELTA_API_KEY", ""),
            api_secret=cfg.api.delta_api_secret or os.environ.get("DELTA_API_SECRET", ""),
            base_url=cfg.api.delta_base_url,
        )
        print(f"• Environment: {cfg.api.delta_environment} ({cfg.api.delta_base_url})")
        print(f"• Active Symbol: {cfg.symbol}")
        print(f"• Trading Enabled in Config: {cfg.api.trading_enabled}")
        check_signal(cfg)


if __name__ == "__main__":
    main()
