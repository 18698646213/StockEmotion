"""Portfolio management with JSON persistence.

Tracks positions, trade history, cash balance, and net-value snapshots.
Data is persisted to ~/.stock-strategy/portfolio.json.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.trading.fees import FeeCalculator, CommissionDetail

logger = logging.getLogger(__name__)

PORTFOLIO_DIR = Path.home() / ".stock-strategy"
PORTFOLIO_FILE = PORTFOLIO_DIR / "portfolio.json"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Position:
    """A single stock position."""
    ticker: str
    market: str            # 'US' or 'CN'
    shares: int = 0
    avg_cost: float = 0.0  # 加权平均成本
    buy_date: str = ""     # ISO date of the latest purchase (for T+1 check)
    realized_pnl: float = 0.0  # 该票已实现盈亏


@dataclass
class Trade:
    """Record of a single executed trade."""
    id: str = ""
    ticker: str = ""
    market: str = ""       # 'US' or 'CN'
    action: str = ""       # 'BUY' or 'SELL'
    shares: int = 0
    price: float = 0.0
    amount: float = 0.0    # shares * price
    commission: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0
    total_fee: float = 0.0
    timestamp: str = ""
    signal_source: str = "manual"  # 'manual', 'signal', 'backtest'


@dataclass
class Snapshot:
    """Net-value snapshot at a point in time."""
    date: str = ""
    total_value: float = 0.0


# ---------------------------------------------------------------------------
# Portfolio class
# ---------------------------------------------------------------------------

class Portfolio:
    """Manages cash, positions, trades, and net-value snapshots."""

    def __init__(self, initial_capital: float = 100_000.0):
        self.initial_capital: float = initial_capital
        self.cash: float = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.snapshots: List[Snapshot] = []
        self._realized_pnl: float = 0.0

    # ----- Trade operations -----

    def buy(
        self,
        ticker: str,
        market: str,
        shares: int,
        price: float,
        fee: CommissionDetail,
        signal_source: str = "manual",
    ) -> Trade:
        """Execute a BUY trade. Assumes checks already passed (balance, limits)."""
        amount = shares * price
        total_cost = amount + fee.total

        # Update cash
        self.cash -= total_cost

        # Update or create position
        pos = self.positions.get(ticker)
        if pos is None:
            pos = Position(ticker=ticker, market=market)
            self.positions[ticker] = pos

        # Update average cost
        old_total = pos.shares * pos.avg_cost
        new_total = old_total + amount
        pos.shares += shares
        pos.avg_cost = round(new_total / pos.shares, 4) if pos.shares > 0 else 0
        pos.buy_date = datetime.now().strftime("%Y-%m-%d")

        trade = Trade(
            id=str(uuid.uuid4())[:8],
            ticker=ticker,
            market=market,
            action="BUY",
            shares=shares,
            price=price,
            amount=round(amount, 4),
            commission=fee.commission,
            stamp_tax=fee.stamp_tax,
            transfer_fee=fee.transfer_fee,
            total_fee=fee.total,
            timestamp=datetime.now().isoformat(),
            signal_source=signal_source,
        )
        self.trades.append(trade)
        return trade

    def sell(
        self,
        ticker: str,
        market: str,
        shares: int,
        price: float,
        fee: CommissionDetail,
        signal_source: str = "manual",
    ) -> Trade:
        """Execute a SELL trade. Assumes checks already passed (holdings, T+1)."""
        amount = shares * price
        net_proceeds = amount - fee.total

        pos = self.positions[ticker]

        # Calculate realized P&L for this sale
        cost_basis = pos.avg_cost * shares
        pnl = net_proceeds - cost_basis + fee.total  # gross pnl (before fees deducted again for tracking)
        # Simpler: realized = (price - avg_cost) * shares - fee
        realized = (price - pos.avg_cost) * shares - fee.total
        self._realized_pnl += realized
        pos.realized_pnl += realized

        # Update cash
        self.cash += net_proceeds

        # Update position
        pos.shares -= shares
        if pos.shares <= 0:
            pos.shares = 0
            pos.avg_cost = 0.0

        trade = Trade(
            id=str(uuid.uuid4())[:8],
            ticker=ticker,
            market=market,
            action="SELL",
            shares=shares,
            price=price,
            amount=round(amount, 4),
            commission=fee.commission,
            stamp_tax=fee.stamp_tax,
            transfer_fee=fee.transfer_fee,
            total_fee=fee.total,
            timestamp=datetime.now().isoformat(),
            signal_source=signal_source,
        )
        self.trades.append(trade)
        return trade

    # ----- Query helpers -----

    def get_position(self, ticker: str) -> Optional[Position]:
        return self.positions.get(ticker)

    def get_active_positions(self) -> List[Position]:
        """Return positions with shares > 0."""
        return [p for p in self.positions.values() if p.shares > 0]

    def get_summary(self, price_map: Optional[Dict[str, float]] = None) -> dict:
        """Compute portfolio summary.

        Args:
            price_map: {ticker: current_price} for unrealized PnL calculation.
                       If None, uses avg_cost as fallback (unrealized = 0).
        """
        if price_map is None:
            price_map = {}

        market_value = 0.0
        unrealized_pnl = 0.0
        positions_detail = []

        for ticker, pos in self.positions.items():
            if pos.shares <= 0:
                continue
            current_price = price_map.get(ticker, pos.avg_cost)
            pos_value = pos.shares * current_price
            pos_unrealized = (current_price - pos.avg_cost) * pos.shares
            market_value += pos_value
            unrealized_pnl += pos_unrealized

            sellable = pos.shares
            if pos.market == "CN" and not FeeCalculator.is_sellable(pos.buy_date, "CN"):
                sellable = 0

            positions_detail.append({
                "ticker": pos.ticker,
                "market": pos.market,
                "shares": pos.shares,
                "avg_cost": round(pos.avg_cost, 4),
                "current_price": round(current_price, 4),
                "unrealized_pnl": round(pos_unrealized, 2),
                "unrealized_pnl_pct": round(pos_unrealized / (pos.avg_cost * pos.shares) * 100, 2) if pos.avg_cost > 0 else 0,
                "sellable_shares": sellable,
            })

        total_value = self.cash + market_value
        total_pnl = total_value - self.initial_capital

        # Win rate based on closed trades
        sell_trades = [t for t in self.trades if t.action == "SELL"]
        wins = sum(1 for t in sell_trades if (t.price - self._get_avg_cost_at_sell(t)) > 0)
        win_rate = round(wins / len(sell_trades) * 100, 1) if sell_trades else 0.0

        return {
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "market_value": round(market_value, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / self.initial_capital * 100, 2) if self.initial_capital > 0 else 0,
            "realized_pnl": round(self._realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "positions": positions_detail,
            "win_rate": win_rate,
            "trade_count": len(self.trades),
        }

    def _get_avg_cost_at_sell(self, trade: Trade) -> float:
        """Estimate avg cost for a sell trade (approximation)."""
        # Use the position's current avg_cost as best estimate
        pos = self.positions.get(trade.ticker)
        return pos.avg_cost if pos else trade.price

    def take_snapshot(self, date: str, price_map: Dict[str, float]):
        """Record a net-value snapshot."""
        summary = self.get_summary(price_map)
        self.snapshots.append(Snapshot(date=date, total_value=summary["total_value"]))

    # ----- Persistence -----

    def save(self):
        """Persist portfolio state to JSON file."""
        PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "realized_pnl": self._realized_pnl,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "trades": [asdict(t) for t in self.trades],
            "snapshots": [asdict(s) for s in self.snapshots],
        }
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Portfolio saved to %s", PORTFOLIO_FILE)

    @classmethod
    def load(cls) -> "Portfolio":
        """Load portfolio from JSON file, or create a new one if not found."""
        if not PORTFOLIO_FILE.exists():
            logger.info("No saved portfolio found, creating new one")
            return cls()

        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            p = cls(initial_capital=data.get("initial_capital", 100_000))
            p.cash = data.get("cash", p.initial_capital)
            p._realized_pnl = data.get("realized_pnl", 0.0)

            for k, v in data.get("positions", {}).items():
                p.positions[k] = Position(**v)

            for t in data.get("trades", []):
                p.trades.append(Trade(**t))

            for s in data.get("snapshots", []):
                p.snapshots.append(Snapshot(**s))

            logger.info("Portfolio loaded: cash=%.2f, %d positions, %d trades",
                        p.cash, len(p.get_active_positions()), len(p.trades))
            return p
        except Exception as e:
            logger.error("Failed to load portfolio: %s", e)
            return cls()
