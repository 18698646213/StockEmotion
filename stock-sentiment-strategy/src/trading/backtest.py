"""Backtesting engine.

Runs a historical simulation: fetches price data for a date range,
computes daily technical signals, executes simulated trades, and
produces a comprehensive report with metrics and equity curve.
"""

import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from src.data.price_us import fetch_us_price
from src.data.price_cn import fetch_cn_price
from src.analysis.technical import compute_indicators, compute_technical_score
from src.analysis.signal import generate_signal
from src.trading.fees import FeeCalculator, CommissionDetail
from src.trading.portfolio import Portfolio, Trade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report data classes
# ---------------------------------------------------------------------------

@dataclass
class BacktestMetrics:
    total_return: float = 0.0       # 总收益率 (%)
    annual_return: float = 0.0      # 年化收益率 (%)
    max_drawdown: float = 0.0       # 最大回撤 (%)
    sharpe_ratio: float = 0.0       # 夏普比率
    win_rate: float = 0.0           # 胜率 (%)
    profit_loss_ratio: float = 0.0  # 盈亏比
    total_trades: int = 0


@dataclass
class BuySellPoint:
    date: str
    action: str   # 'BUY' or 'SELL'
    price: float


@dataclass
class EquityCurvePoint:
    date: str
    value: float


@dataclass
class BacktestReport:
    ticker: str
    market: str
    start_date: str
    end_date: str
    initial_capital: float
    metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    trades: List[dict] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)
    buy_sell_points: List[dict] = field(default_factory=list)
    price_data: List[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Run historical backtests using technical signals."""

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        position_pct: float = 30.0,
    ):
        self.initial_capital = initial_capital
        self.position_pct = position_pct  # Max allocation per trade (%)

    def run(
        self,
        ticker: str,
        market: str,
        start_date: str,
        end_date: str,
    ) -> BacktestReport:
        """Run a backtest for a single ticker over a date range.

        Strategy logic:
          - Use generate_rule_advice() from technical indicators
          - If primary advice is BUY and not currently holding → buy
          - If primary advice is SELL and currently holding → sell
          - Otherwise hold
        """
        logger.info("回测开始: %s (%s) %s ~ %s, 初始资金=%.0f",
                     ticker, market, start_date, end_date, self.initial_capital)

        # 1. Fetch historical price data
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
        total_days = (end_dt - start_dt).days + 60  # extra days for indicator warmup

        if market.upper() == "CN":
            df = fetch_cn_price(ticker, period_days=total_days, interval="daily")
        else:
            df = fetch_us_price(ticker, period_days=total_days, interval="daily")

        if df is None or df.empty:
            logger.warning("回测失败: 无法获取 %s 的价格数据", ticker)
            return BacktestReport(
                ticker=ticker, market=market,
                start_date=start_date, end_date=end_date,
                initial_capital=self.initial_capital,
            )

        # Ensure index is datetime for filtering
        df.index = pd.to_datetime(df.index)

        # 2. Compute indicators on full data
        df = compute_indicators(df)

        # 3. Filter to date range (after indicators are computed for warmup)
        mask = (df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))
        trade_df = df[mask].copy()

        if trade_df.empty:
            logger.warning("回测日期范围内无数据: %s ~ %s", start_date, end_date)
            return BacktestReport(
                ticker=ticker, market=market,
                start_date=start_date, end_date=end_date,
                initial_capital=self.initial_capital,
            )

        # 4. Simulate trading
        portfolio = Portfolio(initial_capital=self.initial_capital)
        trades_list: List[Trade] = []
        buy_sell_points: List[BuySellPoint] = []
        equity_curve: List[EquityCurvePoint] = []

        holding = False

        for i in range(len(trade_df)):
            current_date = trade_df.index[i]
            date_str = current_date.strftime("%Y-%m-%d")
            close_price = float(trade_df.iloc[i]["close"])

            # Get the slice of df up to current date for indicator calculation
            hist_slice = df.loc[:current_date]
            if len(hist_slice) < 30:
                # Not enough data for indicators
                equity_curve.append(EquityCurvePoint(
                    date=date_str,
                    value=round(portfolio.cash + (portfolio.get_position(ticker).shares * close_price if portfolio.get_position(ticker) else 0), 2),
                ).__dict__)
                continue

            # Compute technical score on the historical slice
            tech_scores = compute_technical_score(hist_slice)
            advice_list = tech_scores.get("advice", [])

            # Determine primary advice
            primary_advice = "HOLD"
            if advice_list:
                primary = next(
                    (a for a in advice_list if a["action"] in ("BUY", "SELL")),
                    advice_list[0],
                )
                primary_advice = primary["action"]

            # Also use composite technical score as a secondary signal
            composite = tech_scores.get("composite", 0)

            # Execute based on signal
            pos = portfolio.get_position(ticker)
            current_shares = pos.shares if pos else 0

            if primary_advice == "BUY" and not holding:
                # Calculate shares to buy
                target_amount = portfolio.cash * (self.position_pct / 100.0)
                shares = int(target_amount / close_price)
                if market.upper() == "CN":
                    shares = (shares // 100) * 100
                if shares > 0:
                    fee = FeeCalculator.calc_commission(market, "BUY", shares, close_price)
                    total_cost = shares * close_price + fee.total
                    if total_cost <= portfolio.cash:
                        trade = portfolio.buy(ticker, market, shares, close_price, fee, "backtest")
                        trades_list.append(trade)
                        buy_sell_points.append(BuySellPoint(date=date_str, action="BUY", price=close_price).__dict__)
                        holding = True

            elif primary_advice == "SELL" and holding and current_shares > 0:
                fee = FeeCalculator.calc_commission(market, "SELL", current_shares, close_price)
                trade = portfolio.sell(ticker, market, current_shares, close_price, fee, "backtest")
                trades_list.append(trade)
                buy_sell_points.append(BuySellPoint(date=date_str, action="SELL", price=close_price).__dict__)
                holding = False

            elif composite > 0.5 and not holding:
                # Strong technical bullish — buy
                target_amount = portfolio.cash * (self.position_pct / 100.0)
                shares = int(target_amount / close_price)
                if market.upper() == "CN":
                    shares = (shares // 100) * 100
                if shares > 0:
                    fee = FeeCalculator.calc_commission(market, "BUY", shares, close_price)
                    total_cost = shares * close_price + fee.total
                    if total_cost <= portfolio.cash:
                        trade = portfolio.buy(ticker, market, shares, close_price, fee, "backtest")
                        trades_list.append(trade)
                        buy_sell_points.append(BuySellPoint(date=date_str, action="BUY", price=close_price).__dict__)
                        holding = True

            elif composite < -0.5 and holding and current_shares > 0:
                # Strong technical bearish — sell
                fee = FeeCalculator.calc_commission(market, "SELL", current_shares, close_price)
                trade = portfolio.sell(ticker, market, current_shares, close_price, fee, "backtest")
                trades_list.append(trade)
                buy_sell_points.append(BuySellPoint(date=date_str, action="SELL", price=close_price).__dict__)
                holding = False

            # Record equity
            pos_val = portfolio.get_position(ticker)
            pos_value = pos_val.shares * close_price if pos_val and pos_val.shares > 0 else 0
            total_val = portfolio.cash + pos_value
            equity_curve.append(EquityCurvePoint(date=date_str, value=round(total_val, 2)).__dict__)

        # 5. Force close any remaining position at last price
        final_pos = portfolio.get_position(ticker)
        if final_pos and final_pos.shares > 0:
            last_price = float(trade_df.iloc[-1]["close"])
            last_date = trade_df.index[-1].strftime("%Y-%m-%d")
            fee = FeeCalculator.calc_commission(market, "SELL", final_pos.shares, last_price)
            trade = portfolio.sell(ticker, market, final_pos.shares, last_price, fee, "backtest")
            trades_list.append(trade)
            buy_sell_points.append(BuySellPoint(date=last_date, action="SELL", price=last_price).__dict__)
            # Update last equity point
            if equity_curve:
                equity_curve[-1]["value"] = round(portfolio.cash, 2)

        # 6. Compute metrics
        metrics = self._compute_metrics(equity_curve, trades_list)

        # 7. Convert price data for frontend
        price_bars = []
        for idx, row in trade_df.iterrows():
            price_bars.append({
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(float(row.get("open", 0)), 4),
                "high": round(float(row.get("high", 0)), 4),
                "low": round(float(row.get("low", 0)), 4),
                "close": round(float(row.get("close", 0)), 4),
                "volume": float(row.get("volume", 0)),
            })

        report = BacktestReport(
            ticker=ticker,
            market=market,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            metrics=metrics,
            trades=[asdict(t) for t in trades_list],
            equity_curve=equity_curve,
            buy_sell_points=buy_sell_points,
            price_data=price_bars,
        )

        logger.info("回测完成: %s, 总收益=%.2f%%, 交易次数=%d, 最大回撤=%.2f%%",
                     ticker, metrics.total_return, metrics.total_trades, metrics.max_drawdown)

        return report

    def _compute_metrics(
        self,
        equity_curve: List[dict],
        trades: List[Trade],
    ) -> BacktestMetrics:
        """Calculate backtest performance metrics."""
        if not equity_curve:
            return BacktestMetrics()

        values = [p["value"] for p in equity_curve]
        initial = self.initial_capital
        final = values[-1]

        # Total return
        total_return = (final - initial) / initial * 100

        # Annual return
        num_days = len(equity_curve)
        if num_days > 1 and initial > 0:
            annual_return = ((final / initial) ** (252.0 / num_days) - 1) * 100
        else:
            annual_return = 0.0

        # Max drawdown
        max_drawdown = 0.0
        peak = values[0]
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

        # Sharpe ratio (daily returns, annualized, risk-free rate = 0)
        if len(values) > 1:
            returns = [(values[i] - values[i - 1]) / values[i - 1]
                       for i in range(1, len(values)) if values[i - 1] > 0]
            if returns:
                avg_ret = sum(returns) / len(returns)
                std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5
                sharpe_ratio = (avg_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0.0
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0

        # Win rate and profit/loss ratio
        sell_trades = [t for t in trades if t.action == "SELL"]
        if sell_trades:
            # Pair buy-sell trades
            wins = 0
            total_profit = 0.0
            total_loss = 0.0

            buy_prices = {}
            for t in trades:
                if t.action == "BUY":
                    buy_prices[t.ticker] = t.price
                elif t.action == "SELL" and t.ticker in buy_prices:
                    pnl = (t.price - buy_prices[t.ticker]) * t.shares - t.total_fee
                    if pnl > 0:
                        wins += 1
                        total_profit += pnl
                    else:
                        total_loss += abs(pnl)

            win_rate = wins / len(sell_trades) * 100 if sell_trades else 0
            profit_loss_ratio = (total_profit / total_loss) if total_loss > 0 else (
                float('inf') if total_profit > 0 else 0
            )
        else:
            win_rate = 0.0
            profit_loss_ratio = 0.0

        return BacktestMetrics(
            total_return=round(total_return, 2),
            annual_return=round(annual_return, 2),
            max_drawdown=round(max_drawdown, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            win_rate=round(win_rate, 1),
            profit_loss_ratio=round(profit_loss_ratio, 2) if not math.isinf(profit_loss_ratio) else 999.99,
            total_trades=len(trades),
        )
