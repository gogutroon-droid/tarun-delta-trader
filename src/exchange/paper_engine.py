from datetime import datetime
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

logger = logging.getLogger("Trader.PaperEngine")


class PaperExecutionEngine:

    def __init__(
        self,
        starting_equity: float = 10000.0,
        currency: str = "INR",
        inr_usdt_rate: float = 86.50,
        maker_fee: float = 0.00020,
        taker_fee: float = 0.00030,
        slippage_bps: float = 1.0,
        trade_log_path: str = "reports/paper_trades.csv"
    ):
        self.starting_equity = starting_equity
        self.current_equity = starting_equity
        self.peak_equity = starting_equity
        self.currency = currency.upper()
        self.inr_usdt_rate = inr_usdt_rate
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.slippage_rate = slippage_bps / 10000.0
        self.trade_log_path = trade_log_path

        self.active_trade: Optional[Dict[str, Any]] = None
        self.trade_history: List[Dict[str, Any]] = []

        log_dir = os.path.dirname(trade_log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

    def get_equity(self) -> float:
        return self.current_equity

    def get_open_position(self) -> Optional[Dict[str, Any]]:
        return self.active_trade

    def open_position(
        self,
        signal: Dict[str, Any],
        quantity_contracts: float,
        notional_val_base: float,
        risk_amount_base: float
    ) -> Dict[str, Any]:
        if self.active_trade is not None:
            logger.warning("Cannot open new paper trade: Position already active.")
            return {}

        dir_val = signal["direction"]
        entry_p = signal["entry_price"]
        sl_p = signal["stop_loss"]
        stop_dist = signal["stop_dist"]
        tp_p = signal.get("tp_price", entry_p + (15.0 * stop_dist) if dir_val == "LONG" else entry_p - (15.0 * stop_dist))
        rr_ratio = signal.get("rr_ratio", 15.0)
        max_hold_bars = signal.get("max_hold_bars", 120)
        setup_name = signal.get("setup_name", "MARKOV_15M_PULLBACK")
        trade_id = f"PAPER_{int(time.time())}"

        self.active_trade = {
            "trade_id": trade_id,
            "entry_time": signal.get("datetime", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
            "direction": dir_val,
            "setup": setup_name,
            "entry_price": entry_p,
            "current_sl": sl_p,
            "initial_sl": sl_p,
            "stop_dist": stop_dist,
            "tp_price": tp_p,
            "rr_ratio": rr_ratio,
            "max_hold_bars": max_hold_bars,
            "quantity_contracts": quantity_contracts,
            "notional_val_base": notional_val_base,
            "risk_amount_base": risk_amount_base,
            "bars_held": 0
        }

        print("\n" + "=" * 90)
        print(f" >>> [MODEL B TRADE OPENED] {dir_val} ({setup_name}) <<<")
        print(f"  Entry Price     : ${entry_p:,.2f}")
        print(f"  Stop Loss       : ${sl_p:,.2f} (-1.0R | Dist: ${stop_dist:,.2f})")
        print(f"  Target TP (15R) : ${tp_p:,.2f} (+{rr_ratio:.1f}R Target)")
        print(f"  Max Hold Limit  : {max_hold_bars} Bars (30 Hours Timeout Exit)")
        print(f"  Position Size   : {quantity_contracts} Contracts ({self.currency} {notional_val_base:,.2f} Notional)")
        print(f"  Risk Budget     : {self.currency} {risk_amount_base:,.2f} (3.0% Dynamic Compounding)")
        print("=" * 90 + "\n")

        return self.active_trade

    def increment_candle_bar(self, current_price: float):
        if self.active_trade is None:
            return

        self.active_trade["bars_held"] += 1
        bars_held = self.active_trade["bars_held"]
        max_bars = self.active_trade["max_hold_bars"]

        if bars_held >= max_bars:
            self._close_position(
                exit_price=current_price,
                reason=f"TIMEOUT_EXIT ({bars_held} Bars / 30 Hours Reached)",
                is_timeout=True
            )

    def update_price(self, current_price: float):
        if self.active_trade is None:
            return

        trade = self.active_trade
        dir_val = trade["direction"]
        curr_sl = trade["current_sl"]
        tp_p = trade["tp_price"]

        tp_reached = (current_price >= tp_p) if dir_val == "LONG" else (current_price <= tp_p)
        if tp_reached:
            self._close_position(
                exit_price=tp_p,
                reason=f"TP_FULL (+{trade['rr_ratio']:.1f}R Target Hit)",
                runner_realized_r=trade["rr_ratio"]
            )
            return

        sl_hit = (current_price <= curr_sl) if dir_val == "LONG" else (current_price >= curr_sl)
        if sl_hit:
            self._close_position(
                exit_price=curr_sl,
                reason="SL_FULL (-1.0R Stop Loss Hit)",
                runner_realized_r=-1.00
            )

    def _close_position(
        self,
        exit_price: float,
        reason: str,
        runner_realized_r: float = 0.0,
        is_timeout: bool = False
    ):
        trade = self.active_trade
        if trade is None:
            return

        dir_val = trade["direction"]
        risk_base = trade["risk_amount_base"]
        entry_p = trade["entry_price"]
        entry_notional = trade["notional_val_base"]

        if is_timeout:
            if dir_val == "LONG":
                pct_change = (exit_price - entry_p) / entry_p if entry_p > 0 else 0.0
            else:
                pct_change = (entry_p - exit_price) / entry_p if entry_p > 0 else 0.0
            gross_pnl = pct_change * entry_notional
            realized_r = gross_pnl / risk_base if risk_base > 0 else 0.0
        else:
            gross_pnl = runner_realized_r * risk_base
            realized_r = runner_realized_r

        entry_fee = entry_notional * self.maker_fee
        exit_notional = entry_notional * (exit_price / entry_p) if entry_p > 0 else entry_notional
        exit_fee = exit_notional * self.taker_fee
        slippage_cost = (entry_notional + exit_notional) * self.slippage_rate
        total_friction = entry_fee + exit_fee + slippage_cost

        net_pnl = gross_pnl - total_friction
        self.current_equity += net_pnl
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        drawdown_pct = ((self.peak_equity - self.current_equity) / self.peak_equity) * 100.0

        closed_record = {
            "trade_id": trade["trade_id"],
            "entry_time": trade["entry_time"],
            "exit_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "direction": dir_val,
            "setup": trade["setup"],
            "entry_price": entry_p,
            "exit_price": exit_price,
            "stop_loss": trade["initial_sl"],
            "take_profit": trade["tp_price"],
            "reason": reason,
            "realized_r": realized_r,
            "bars_held": trade["bars_held"],
            "gross_pnl": gross_pnl,
            "friction": total_friction,
            "net_pnl": net_pnl,
            "equity": self.current_equity,
            "drawdown_pct": drawdown_pct
        }

        self.trade_history.append(closed_record)
        self.active_trade = None

        print("\n" + "=" * 90)
        pnl_symbol = "🟢 +" if net_pnl >= 0 else "🔴 "
        print(f" >>> [MODEL B TRADE CLOSED] {dir_val} ({reason}) <<<")
        print(f"  Entry Price     : ${entry_p:,.2f} -> Exit: ${exit_price:,.2f}")
        print(f"  Realized R      : {realized_r:+.2f}R | Bars Held: {trade['bars_held']}")
        print(f"  Gross PnL       : {self.currency} {gross_pnl:+,.2f}")
        print(f"  Friction        : {self.currency} {total_friction:,.2f}")
        print(f"  Net PnL         : {pnl_symbol}{self.currency} {net_pnl:+,.2f}")
        print(f"  Updated Equity  : {self.currency} {self.current_equity:,.2f} (DD: -{drawdown_pct:.2f}%)")
        print("=" * 90 + "\n")

        try:
            df_rec = pd.DataFrame([closed_record])
            if not os.path.exists(self.trade_log_path):
                df_rec.to_csv(self.trade_log_path, index=False)
            else:
                df_rec.to_csv(self.trade_log_path, mode="a", header=False, index=False)
        except Exception as e:
            logger.error(f"Failed to append to paper trade log: {e}")

        return closed_record
