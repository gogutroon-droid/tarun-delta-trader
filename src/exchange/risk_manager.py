import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("Trader.RiskManager")


class RiskLimitsException(Exception):
    pass


class DeltaRiskManager:

    def __init__(
        self,
        starting_equity: float = 10000.0,
        risk_pct: float = 0.050,
        currency: str = "INR",
        inr_usdt_rate: float = 86.50,
        max_daily_loss_pct: float = 0.10,
        max_leverage: int = 10,
        max_open_positions: int = 1,
        min_notional_usdt: float = 5.0,
        contract_lot_size: float = 1.0
    ):
        self.starting_equity = float(starting_equity)
        self.current_equity = float(starting_equity)
        self.daily_start_equity = float(starting_equity)
        self.risk_pct = float(risk_pct)
        self.currency = currency.upper().strip()
        self.inr_usdt_rate = float(inr_usdt_rate)
        self.max_daily_loss_pct = float(max_daily_loss_pct)
        self.max_leverage = int(max_leverage)
        self.max_open_positions = int(max_open_positions)
        self.min_notional_usdt = float(min_notional_usdt)
        self.contract_lot_size = float(contract_lot_size)

        self.consecutive_losses = 0
        self.circuit_breaker_active = False

    def update_equity(self, current_equity: float):
        self.current_equity = float(current_equity)

        if self.daily_start_equity > 0:
            daily_loss_ratio = (self.daily_start_equity - self.current_equity) / self.daily_start_equity
            if daily_loss_ratio >= self.max_daily_loss_pct:
                self.circuit_breaker_active = True
                logger.critical(
                    f"[CIRCUIT BREAKER TRIGGERED] Intraday account loss ({daily_loss_ratio * 100:.2f}%) "
                    f"exceeded maximum allowed limit ({self.max_daily_loss_pct * 100:.1f}%). All trading halted."
                )

    def reset_daily_benchmark(self):
        self.daily_start_equity = self.current_equity
        self.circuit_breaker_active = False
        logger.info(f"Daily equity benchmark reset to {self.currency} {self.daily_start_equity:,.2f}.")

    def register_trade_outcome(self, net_pnl: float):
        if net_pnl <= 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def record_trade_result(self, net_pnl: float):
        self.register_trade_outcome(net_pnl)
        self.update_equity(self.current_equity + net_pnl)

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        product_info: Optional[Dict[str, Any]] = None,
        active_position_count: int = 0
    ) -> Tuple[int, float, float]:
        if self.circuit_breaker_active:
            raise RiskLimitsException("Trade rejected: Intraday loss circuit breaker is active.")

        if active_position_count >= self.max_open_positions:
            raise RiskLimitsException(
                f"Trade rejected: Maximum allowed open positions ({self.max_open_positions}) reached."
            )

        if entry_price <= 0 or stop_loss_price <= 0:
            raise RiskLimitsException(f"Invalid prices: Entry={entry_price}, SL={stop_loss_price}")

        stop_dist = abs(entry_price - stop_loss_price)
        if stop_dist <= 0:
            raise RiskLimitsException("Stop loss distance must be greater than zero.")

        stop_dist_pct = stop_dist / entry_price

        risk_budget_base = self.current_equity * self.risk_pct
        if risk_budget_base <= 0:
            raise RiskLimitsException("Insufficient equity to allocate risk budget.")

        notional_base = risk_budget_base / stop_dist_pct

        if self.currency == "INR":
            equity_usdt = self.current_equity / self.inr_usdt_rate
            notional_usdt = notional_base / self.inr_usdt_rate
        else:
            equity_usdt = self.current_equity
            notional_usdt = notional_base

        max_notional_allowed = equity_usdt * self.max_leverage
        if notional_usdt > max_notional_allowed:
            logger.info(
                f"Notional ${notional_usdt:,.2f} exceeds {self.max_leverage}x leverage limit (${max_notional_allowed:,.2f}). "
                "Capping notional to maximum allowable leverage."
            )
            notional_usdt = max_notional_allowed
            notional_base = notional_usdt * (self.inr_usdt_rate if self.currency == "INR" else 1.0)

        contract_value_usd = 1.0
        if product_info:
            contract_value_usd = float(product_info.get("contract_value", 1.0))
            if contract_value_usd <= 0:
                contract_value_usd = 1.0

        raw_contracts = notional_usdt / contract_value_usd
        contracts = max(1, int(raw_contracts))

        actual_notional_usdt = contracts * contract_value_usd
        if actual_notional_usdt < self.min_notional_usdt:
            logger.warning(
                f"Position notional ${actual_notional_usdt:.2f} is below exchange minimum threshold (${self.min_notional_usdt:.2f})."
            )
            return 0, 0.0, 0.0

        actual_notional_base = actual_notional_usdt * (self.inr_usdt_rate if self.currency == "INR" else 1.0)
        return contracts, actual_notional_base, risk_budget_base

    def validate_grid_order(
        self,
        contracts_to_buy: float,
        current_inventory: float,
        max_inventory: float
    ) -> bool:
        if self.circuit_breaker_active:
            logger.warning("[GRID RISK] Order blocked: Circuit breaker active.")
            return False

        if (current_inventory + contracts_to_buy) > max_inventory:
            logger.warning(
                f"[GRID RISK] Order blocked: Proposed inventory ({current_inventory + contracts_to_buy:.1f}) "
                f"exceeds max inventory cap ({max_inventory:.1f})."
            )
            return False

        return True

    def calculate_grid_allocation(self, capital_fraction: float = 0.50) -> float:
        return self.current_equity * min(1.0, max(0.05, capital_fraction))
