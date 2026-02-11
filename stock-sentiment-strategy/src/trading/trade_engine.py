"""Trade execution engine.

Combines Portfolio + FeeCalculator to execute manual and signal-driven trades
with proper validation (balance, holdings, T+1, price limits).
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.trading.fees import FeeCalculator, CommissionDetail
from src.trading.portfolio import Portfolio, Trade

logger = logging.getLogger(__name__)


@dataclass
class TradeResult:
    """Result of a trade execution attempt."""
    success: bool
    trade: Optional[Trade] = None
    error_msg: str = ""
    fee_detail: Optional[CommissionDetail] = None


class TradeEngine:
    """Execute and validate simulated trades."""

    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio

    # ----- Manual trades -----

    def execute_buy(
        self,
        ticker: str,
        market: str,
        shares: int,
        price: float,
        signal_source: str = "manual",
    ) -> TradeResult:
        """Execute a BUY order with full validation."""
        if shares <= 0:
            return TradeResult(success=False, error_msg="股数必须大于 0")
        if price <= 0:
            return TradeResult(success=False, error_msg="价格必须大于 0")

        # A-share: must buy in lots of 100
        if market.upper() == "CN" and shares % 100 != 0:
            return TradeResult(success=False, error_msg="A 股买入必须为 100 的整数倍")

        # Calculate fees
        fee = FeeCalculator.calc_commission(market, "BUY", shares, price)
        total_cost = shares * price + fee.total

        # Check balance
        if total_cost > self.portfolio.cash:
            return TradeResult(
                success=False,
                error_msg=f"资金不足: 需要 {total_cost:.2f}, 可用 {self.portfolio.cash:.2f}",
                fee_detail=fee,
            )

        # Execute
        trade = self.portfolio.buy(ticker, market, shares, price, fee, signal_source)
        self.portfolio.save()

        logger.info("BUY %s x%d @%.2f, fee=%.2f, source=%s",
                     ticker, shares, price, fee.total, signal_source)

        return TradeResult(success=True, trade=trade, fee_detail=fee)

    def execute_sell(
        self,
        ticker: str,
        market: str,
        shares: int,
        price: float,
        signal_source: str = "manual",
    ) -> TradeResult:
        """Execute a SELL order with full validation."""
        if shares <= 0:
            return TradeResult(success=False, error_msg="股数必须大于 0")
        if price <= 0:
            return TradeResult(success=False, error_msg="价格必须大于 0")

        # Check holdings
        pos = self.portfolio.get_position(ticker)
        if pos is None or pos.shares <= 0:
            return TradeResult(success=False, error_msg=f"未持有 {ticker}")

        if shares > pos.shares:
            return TradeResult(
                success=False,
                error_msg=f"持仓不足: 需卖出 {shares} 股, 持有 {pos.shares} 股",
            )

        # T+1 check for A-shares
        if market.upper() == "CN" and not FeeCalculator.is_sellable(pos.buy_date, "CN"):
            return TradeResult(
                success=False,
                error_msg=f"T+1 限制: {ticker} 今日买入不可当日卖出",
            )

        # Calculate fees
        fee = FeeCalculator.calc_commission(market, "SELL", shares, price)

        # Execute
        trade = self.portfolio.sell(ticker, market, shares, price, fee, signal_source)
        self.portfolio.save()

        logger.info("SELL %s x%d @%.2f, fee=%.2f, source=%s",
                     ticker, shares, price, fee.total, signal_source)

        return TradeResult(success=True, trade=trade, fee_detail=fee)

    # ----- Signal-driven trade -----

    def execute_signal_trade(
        self,
        ticker: str,
        market: str,
        signal: str,
        composite_score: float,
        position_pct: float,
        price: float,
    ) -> TradeResult:
        """Execute a trade based on analysis signal.

        For BUY/STRONG_BUY: allocate position_pct of total portfolio value.
        For SELL/STRONG_SELL: sell entire holding.
        For HOLD: do nothing.
        """
        if signal in ("HOLD",):
            return TradeResult(success=True, error_msg="信号为持有，不执行交易")

        if signal in ("BUY", "STRONG_BUY"):
            # Calculate target allocation
            total_value = self.portfolio.cash
            for pos in self.portfolio.get_active_positions():
                total_value += pos.shares * pos.avg_cost  # approximate

            if position_pct <= 0:
                return TradeResult(success=True, error_msg="建议仓位为 0，不执行买入")

            target_amount = total_value * (position_pct / 100.0)
            # Already holding? Calculate additional amount
            pos = self.portfolio.get_position(ticker)
            current_value = (pos.shares * price) if pos and pos.shares > 0 else 0
            additional = target_amount - current_value

            if additional <= 0:
                return TradeResult(success=True, error_msg="已达到或超过目标仓位，不再加仓")

            # Calculate shares
            shares = int(additional / price)
            if market.upper() == "CN":
                shares = (shares // 100) * 100  # Round to lots of 100

            if shares <= 0:
                return TradeResult(success=True, error_msg="计算买入股数为 0，不执行")

            return self.execute_buy(ticker, market, shares, price, signal_source="signal")

        if signal in ("SELL", "STRONG_SELL"):
            pos = self.portfolio.get_position(ticker)
            if pos is None or pos.shares <= 0:
                return TradeResult(success=True, error_msg=f"未持有 {ticker}，无法卖出")

            return self.execute_sell(ticker, market, pos.shares, price, signal_source="signal")

        return TradeResult(success=False, error_msg=f"未知信号类型: {signal}")

    # ----- Fee preview -----

    @staticmethod
    def preview_fee(
        market: str,
        action: str,
        shares: int,
        price: float,
    ) -> CommissionDetail:
        """Preview trade fees without executing."""
        return FeeCalculator.calc_commission(market, action, shares, price)
