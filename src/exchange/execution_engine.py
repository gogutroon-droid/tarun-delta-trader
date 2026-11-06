from datetime import datetime
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from .delta_client import DeltaExchangeClient, DeltaAPIException, DeltaSecurityException
from .risk_manager import DeltaRiskManager, RiskLimitsException

logger = logging.getLogger("Trader.ExecutionEngine")


class DeltaExecutionEngine:

    def __init__(
        self,
        client: DeltaExchangeClient,
        risk_manager: DeltaRiskManager,
        symbol: str = "BTCUSD",
        currency: str = "INR",
        inr_usdt_rate: float = 86.50,
        trade_log_path: str = "reports/live_testnet_trades.csv"
    ):
        self.client = client
        self.risk_manager = risk_manager
        self.symbol = symbol.upper().strip()
        self.currency = currency.upper().strip()
        self.inr_usdt_rate = inr_usdt_rate
        self.trade_log_path = trade_log_path

        self.active_position: Optional[Dict[str, Any]] = None
        self.trade_history: List[Dict[str, Any]] = []

        log_dir = os.path.dirname(trade_log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

    def is_trading_enabled(self) -> bool:
        return self.client.trading_enabled

    def execute_entry_signal(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.client.trading_enabled:
            logger.warning(
                "[SAFETY LOCK] Order placement skipped: TRADING_ENABLED=false. "
                "To submit live testnet orders, enable trading explicitly."
            )
            return None

        if self.active_position is not None:
            logger.warning("Trade skipped: A position is already active locally.")
            return None

        prod_info = self.client.get_product(self.symbol)
        if not prod_info:
            logger.error(f"Cannot execute trade: Product info for {self.symbol} not available.")
            return None

        dir_val = signal["direction"]
        entry_p = signal["entry_price"]
        sl_p = signal["stop_loss"]
        stop_dist = signal["stop_dist"]
        tp_p = signal.get("tp_price", signal.get("tp2_price", entry_p + (15.0 * stop_dist) if dir_val == "LONG" else entry_p - (15.0 * stop_dist)))
        rr_ratio = signal.get("rr_ratio", 15.0)
        max_hold_bars = signal.get("max_hold_bars", 120)
        setup_name = signal.get("setup_name", "MARKOV_15M_PULLBACK")

        try:
            contracts, notional_base, risk_base = self.risk_manager.calculate_position_size(
                entry_price=entry_p,
                stop_loss_price=sl_p,
                product_info=prod_info,
                active_position_count=1 if self.active_position else 0
            )
        except RiskLimitsException as e:
            logger.warning(f"Trade blocked by Risk Manager: {e}")
            return None

        if contracts <= 0:
            logger.warning("Calculated contract size is 0. Trade skipped.")
            return None

        client_oid = f"TRADER_{int(time.time())}_{dir_val}_{setup_name[:8]}"
        order_side = "buy" if dir_val == "LONG" else "sell"

        logger.info(
            f"[TESTNET ORDER] Submitting MARKET {order_side.upper()} order for {contracts} contracts "
            f"on {self.symbol} (~${entry_p:,.2f}) | ClientOID: {client_oid}..."
        )

        try:
            order_res = self.client.place_order(
                symbol=self.symbol,
                size=contracts,
                side=order_side,
                order_type="market_order",
                client_order_id=client_oid
            )
            logger.info(f"[TESTNET FILL] Order accepted by Delta: {order_res.get('id') or order_res}")
        except DeltaSecurityException as e:
            logger.critical(f"[SECURITY HALT] Order aborted by client security guard: {e}")
            return None
        except DeltaAPIException as e:
            logger.error(f"[ORDER REJECTED] Delta Exchange error: {e}")
            return None
        except Exception as e:
            logger.error(f"[ORDER FAILED] Unexpected error during execution: {e}")
            return None

        self.active_position = {
            "trade_id": client_oid,
            "order_id": order_res.get("id"),
            "entry_time": signal.get("datetime", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
            "direction": dir_val,
            "setup": setup_name,
            "entry_price": entry_p,
            "current_sl": sl_p,
            "initial_sl": sl_p,
            "stop_dist": stop_dist,
            "tp_price": tp_p,
            "tp1_price": signal.get("tp1_price", tp_p),
            "tp2_price": tp_p,
            "rr_ratio": rr_ratio,
            "max_hold_bars": max_hold_bars,
            "bars_held": 0,
            "contracts": contracts,
            "notional_base": notional_base,
            "risk_base": risk_base,
            "remaining_share": 1.0,
            "locked_profit_base": 0.0
        }

        print("\n" + "!" * 90)
        print(f" >>> [DELTA TESTNET TRADE EXECUTED] {dir_val} ({setup_name}) <<<")
        print(f"  Symbol          : {self.symbol} (DEMO)")
        print(f"  Entry Price     : ${entry_p:,.2f}")
        print(f"  Stop Loss       : ${sl_p:,.2f} (-1.0R | Dist: ${stop_dist:,.2f})")
        print(f"  Target TP (15R) : ${tp_p:,.2f} (+{rr_ratio:.1f}R Asymmetric Target)")
        print(f"  Timeout Limit   : {max_hold_bars} Bars (30 Hours Timeout Exit)")
        print(f"  Contracts       : {contracts} contracts ({self.currency} {notional_base:,.2f} Notional)")
        print(f"  Risk Budget     : {self.currency} {risk_base:,.2f} (3.0% Risk Compounding)")
        print("!" * 90 + "\n")

        return self.active_position

    def increment_candle_bar(self, current_price: float):
        if self.active_position is None:
            return

        self.active_position["bars_held"] += 1
        bars_held = self.active_position["bars_held"]
        max_bars = self.active_position["max_hold_bars"]

        if bars_held >= max_bars:
            self._close_testnet_position(
                exit_price=current_price,
                reason=f"TIMEOUT_EXIT ({bars_held} Bars / 30 Hours Reached)",
                is_timeout=True
            )

    def manage_active_position(self, current_price: float):
        if self.active_position is None:
            return

        pos = self.active_position
        dir_val = pos["direction"]
        curr_sl = pos["current_sl"]
        tp_p = pos["tp_price"]

        tp_reached = (current_price >= tp_p) if dir_val == "LONG" else (current_price <= tp_p)
        if tp_reached:
            self._close_testnet_position(
                exit_price=tp_p,
                reason=f"TP_FULL (+{pos['rr_ratio']:.1f}R Institutional Target Hit)",
                runner_realized_r=pos["rr_ratio"]
            )
            return

        sl_hit = (current_price <= curr_sl) if dir_val == "LONG" else (current_price >= curr_sl)
        if sl_hit:
            self._close_testnet_position(
                exit_price=curr_sl,
                reason="SL_FULL (-1.0R Stop Loss Hit)",
                runner_realized_r=-1.00
            )

    def _close_testnet_position(
        self,
        exit_price: float,
        reason: str,
        runner_realized_r: float = 0.0,
        is_timeout: bool = False
    ):
        pos = self.active_position
        if pos is None:
            return

        dir_val = pos["direction"]
        contracts = pos["contracts"]
        risk_base = pos["risk_base"]
        entry_p = pos["entry_price"]
        entry_notional = pos["notional_base"]

        if self.client.trading_enabled:
            exit_side = "sell" if dir_val == "LONG" else "buy"
            try:
                self.client.place_order(
                    symbol=self.symbol,
                    size=contracts,
                    side=exit_side,
                    order_type="market_order",
                    reduce_only=True
                )
                logger.info(f"[TESTNET EXIT] Position closed ({reason}) on Delta Exchange.")
            except Exception as e:
                logger.error(f"Failed to submit market close order to Delta: {e}")

        if is_timeout:
            pct_change = (exit_price - entry_p) / entry_p if dir_val == "LONG" else (entry_p - exit_price) / entry_p
            gross_pnl = pct_change * entry_notional
        else:
            gross_pnl = runner_realized_r * risk_base

        maker_fee = entry_notional * 0.00020
        exit_notional = entry_notional * (exit_price / entry_p) if entry_p > 0 else entry_notional
        taker_fee = exit_notional * 0.00030
        slip_cost = (entry_notional + exit_notional) * 0.00005
        total_friction = maker_fee + taker_fee + slip_cost

        net_pnl = gross_pnl - total_friction
        self.risk_manager.record_trade_result(net_pnl)

        record = {
            "trade_id": pos["trade_id"],
            "entry_time": pos["entry_time"],
            "exit_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": self.symbol,
            "direction": dir_val,
            "setup": pos["setup"],
            "entry_price": round(entry_p, 2),
            "exit_price": round(exit_price, 2),
            "initial_sl": round(pos["initial_sl"], 2),
            "contracts": contracts,
            "notional_value": round(entry_notional, 2),
            "gross_pnl": round(gross_pnl, 2),
            "total_friction": round(total_friction, 2),
            "net_pnl": round(net_pnl, 2),
            "outcome": reason,
            "bars_held": pos["bars_held"],
            "account_equity": round(self.risk_manager.current_equity, 2)
        }

        self.trade_history.append(record)
        self.active_position = None

        print("\n" + "!" * 90)
        print(f" <<< [DELTA TESTNET POSITION CLOSED] {reason} >>>")
        print(f"  Exit Price      : ${exit_price:,.2f}")
        print(f"  Gross PnL       : {self.currency} {gross_pnl:>+10,.2f}")
        print(f"  Total Friction  : {self.currency} {total_friction:>10,.2f}")
        print(f"  Net Profit      : {self.currency} {net_pnl:>+10,.2f}")
        print(f"  Updated Equity  : {self.currency} {self.risk_manager.current_equity:,.2f}")
        print("!" * 90 + "\n")

        try:
            df_hist = pd.DataFrame(self.trade_history)
            df_hist.to_csv(self.trade_log_path, index=False)
        except Exception as e:
            logger.error(f"Failed to export testnet trade log: {e}")
