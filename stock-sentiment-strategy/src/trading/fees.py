"""Fee calculator and market rule enforcement for simulated trading.

Supports:
  - A-share: commission (0.025%, min 5 CNY), stamp tax (0.05%, sell only),
    transfer fee (0.001%), price-limit check, T+1 rule.
  - US stock: zero commission (default) or per-share fee.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class CommissionDetail:
    """Breakdown of a single trade's fees."""
    commission: float = 0.0    # 佣金
    stamp_tax: float = 0.0     # 印花税（仅 A 股卖出）
    transfer_fee: float = 0.0  # 过户费（仅 A 股）
    total: float = 0.0

    def __post_init__(self):
        self.total = round(self.commission + self.stamp_tax + self.transfer_fee, 4)


class FeeCalculator:
    """Calculate trade fees and enforce market rules."""

    # ---- A-share fee rates ----
    CN_COMMISSION_RATE = 0.00025     # 万2.5
    CN_MIN_COMMISSION = 5.0          # 最低 5 元
    CN_STAMP_TAX_RATE = 0.0005      # 印花税 0.05%（仅卖出）
    CN_TRANSFER_FEE_RATE = 0.00001  # 过户费 0.001%

    # ---- US stock fee rates ----
    US_PER_SHARE_FEE = 0.0  # 零佣金（可设为 0.005 模拟按股收费）

    # ---- Futures fee rates ----
    FUTURES_COMMISSION_RATE = 0.0001  # 万分之一（双边）

    # ---- A-share price-limit thresholds ----
    # 创业板 (300xxx) / 科创板 (688xxx): ±20%
    # 主板: ±10%
    CHINEXT_PREFIXES = ("300",)
    STAR_PREFIXES = ("688",)

    @classmethod
    def calc_commission(
        cls,
        market: str,
        action: str,
        shares: int,
        price: float,
    ) -> CommissionDetail:
        """Calculate fees for a single trade.

        Args:
            market: 'US' or 'CN'.
            action: 'BUY' or 'SELL'.
            shares: Number of shares.
            price: Price per share.

        Returns:
            CommissionDetail with full breakdown.
        """
        amount = shares * price

        if market.upper() == "CN":
            commission = max(amount * cls.CN_COMMISSION_RATE, cls.CN_MIN_COMMISSION)
            stamp_tax = amount * cls.CN_STAMP_TAX_RATE if action.upper() == "SELL" else 0.0
            transfer_fee = amount * cls.CN_TRANSFER_FEE_RATE
            return CommissionDetail(
                commission=round(commission, 4),
                stamp_tax=round(stamp_tax, 4),
                transfer_fee=round(transfer_fee, 4),
            )
        elif market.upper() == "FUTURES":
            # Futures: simplified commission (双边万分之一)
            commission = amount * cls.FUTURES_COMMISSION_RATE
            return CommissionDetail(commission=round(commission, 4))
        else:
            # US: zero or per-share
            commission = shares * cls.US_PER_SHARE_FEE
            return CommissionDetail(commission=round(commission, 4))

    @classmethod
    def get_price_limit_pct(cls, code: str) -> float:
        """Return the price-limit percentage for a given A-share code.

        Returns:
            0.20 for ChiNext / STAR, 0.10 for main board.
        """
        code_str = str(code).zfill(6)
        if code_str.startswith(cls.CHINEXT_PREFIXES) or code_str.startswith(cls.STAR_PREFIXES):
            return 0.20
        return 0.10

    @classmethod
    def check_price_limit(cls, code: str, price: float, prev_close: float) -> bool:
        """Check whether `price` is within the price-limit band.

        Returns:
            True if within limits (trade allowed), False if breached.
        """
        if prev_close <= 0:
            return True

        limit = cls.get_price_limit_pct(code)
        upper = round(prev_close * (1 + limit), 2)
        lower = round(prev_close * (1 - limit), 2)
        return lower <= price <= upper

    @classmethod
    def is_sellable(cls, buy_date: str, market: str) -> bool:
        """Check T+1 rule: A-share bought today cannot be sold until next trading day.

        Args:
            buy_date: ISO date string of when shares were bought (YYYY-MM-DD).
            market: 'US' or 'CN'.

        Returns:
            True if shares can be sold today.
        """
        if market.upper() != "CN":
            return True  # US / FUTURES: T+0

        try:
            bought = datetime.fromisoformat(buy_date).date()
        except (ValueError, TypeError):
            return True

        today = datetime.now().date()
        return today > bought
