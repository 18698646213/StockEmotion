#!/usr/bin/env python3
"""量化交易策略分析模块.

从 auto_decisions.json 和 auto_positions.json 中提取交易数据，
分析交易策略的各项参数、技术指标使用情况、风控规则等。
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

console = Console()

DATA_DIR = Path(__file__).resolve().parent.parent / "stock-sentiment-strategy" / "data"
SRC_DIR = Path(__file__).resolve().parent.parent / "stock-sentiment-strategy" / "src"


def load_decisions() -> list[dict]:
    path = DATA_DIR / "auto_decisions.json"
    if not path.exists():
        console.print(f"[red]找不到文件: {path}")
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_positions() -> dict:
    path = DATA_DIR / "auto_positions.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config() -> dict:
    path = DATA_DIR.parent / "config.yaml"
    if not path.exists():
        return {}
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def analyze_decisions(decisions: list[dict]) -> None:
    """分析所有交易决策数据."""
    if not decisions:
        console.print("[yellow]无交易决策数据")
        return

    df = pd.DataFrame(decisions)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # ======================================================================
    # 1. 交易品种概况
    # ======================================================================
    console.rule("[bold cyan]一、交易品种概况")

    symbols = df["symbol"].unique().tolist()
    symbol_counts = df["symbol"].value_counts()

    t = Table(title="交易品种统计")
    t.add_column("合约代码", style="cyan")
    t.add_column("品种名称", style="green")
    t.add_column("决策次数", style="yellow", justify="right")
    t.add_column("价格范围", style="white")
    t.add_column("ATR 范围", style="white")

    SYMBOL_NAMES = {
        "C2605": "玉米 2605",
        "SA2605": "纯碱 2605",
    }

    for sym in symbols:
        sub = df[df["symbol"] == sym]
        name = SYMBOL_NAMES.get(sym, sym)
        price_min, price_max = sub["price"].min(), sub["price"].max()
        atr_min, atr_max = sub["atr"].min(), sub["atr"].max()
        t.add_row(
            sym, name, str(len(sub)),
            f"{price_min:.0f} - {price_max:.0f}",
            f"{atr_min:.1f} - {atr_max:.1f}",
        )
    console.print(t)

    # ======================================================================
    # 2. 信号与决策统计
    # ======================================================================
    console.rule("[bold cyan]二、信号与决策统计")

    action_counts = df["action"].value_counts()
    signal_counts = df["signal"].value_counts()

    t2 = Table(title="决策动作分布")
    t2.add_column("动作", style="cyan")
    t2.add_column("次数", style="yellow", justify="right")
    t2.add_column("占比", style="green", justify="right")
    for action, count in action_counts.items():
        t2.add_row(action, str(count), f"{count/len(df)*100:.1f}%")
    console.print(t2)

    t3 = Table(title="信号类型分布")
    t3.add_column("信号", style="cyan")
    t3.add_column("次数", style="yellow", justify="right")
    for sig, count in signal_counts.items():
        t3.add_row(sig, str(count))
    console.print(t3)

    # ======================================================================
    # 3. 综合评分分析
    # ======================================================================
    console.rule("[bold cyan]三、综合评分 (composite_score) 分析")

    for sym in symbols:
        sub = df[df["symbol"] == sym]
        scores = sub["composite_score"]
        console.print(f"\n[bold]{sym} ({SYMBOL_NAMES.get(sym, sym)}):")
        console.print(f"  评分范围: [{scores.min():.2f}, {scores.max():.2f}]")
        console.print(f"  平均评分: {scores.mean():.4f}")
        console.print(f"  标准差:   {scores.std():.4f}")

        hold_reasons = sub[sub["action"] == "HOLD"]["reason"].tolist()
        threshold_msgs = [r for r in hold_reasons if "未达阈值" in r]
        if threshold_msgs:
            thresholds = set()
            for msg in threshold_msgs:
                import re
                m = re.search(r"未达阈值\s*([\d.]+)", msg)
                if m:
                    thresholds.add(m.group(1))
            console.print(f"  信号阈值: {', '.join(thresholds)}")
            console.print(f"  未达阈值次数: {len(threshold_msgs)}/{len(sub)}")

    # ======================================================================
    # 4. ATR 与风控参数
    # ======================================================================
    console.rule("[bold cyan]四、ATR 与风控参数分析")

    t4 = Table(title="ATR (Average True Range) 统计")
    t4.add_column("合约", style="cyan")
    t4.add_column("ATR 均值", style="green", justify="right")
    t4.add_column("ATR 标准差", style="yellow", justify="right")
    t4.add_column("ATR 最小", justify="right")
    t4.add_column("ATR 最大", justify="right")

    for sym in symbols:
        sub = df[df["symbol"] == sym]
        atr = sub["atr"]
        t4.add_row(
            sym,
            f"{atr.mean():.2f}",
            f"{atr.std():.2f}",
            f"{atr.min():.2f}",
            f"{atr.max():.2f}",
        )
    console.print(t4)

    # 止盈止损统计
    pos_with_sl = df[df["stop_loss"] > 0]
    if not pos_with_sl.empty:
        t5 = Table(title="止盈止损设置")
        t5.add_column("合约", style="cyan")
        t5.add_column("止损价", style="red", justify="right")
        t5.add_column("止盈价", style="green", justify="right")
        t5.add_column("入场价", style="white", justify="right")
        t5.add_column("止损幅度", style="red", justify="right")
        t5.add_column("止盈幅度", style="green", justify="right")

        for _, row in pos_with_sl.drop_duplicates(subset=["symbol", "stop_loss"]).iterrows():
            sl_pct = abs(row["stop_loss"] - row["price"]) / row["price"] * 100
            tp_pct = abs(row["take_profit"] - row["price"]) / row["price"] * 100 if row["take_profit"] > 0 else 0
            t5.add_row(
                row["symbol"],
                f"{row['stop_loss']:.1f}",
                f"{row['take_profit']:.1f}",
                f"{row['price']:.1f}",
                f"{sl_pct:.2f}%",
                f"{tp_pct:.2f}%",
            )
        console.print(t5)

    # ======================================================================
    # 5. 时间分析
    # ======================================================================
    console.rule("[bold cyan]五、交易时间分析")

    df["date"] = df["timestamp"].dt.date
    df["hour"] = df["timestamp"].dt.hour

    date_counts = df.groupby("date").size()
    console.print(f"交易日期范围: {date_counts.index.min()} ~ {date_counts.index.max()}")
    console.print(f"交易天数: {len(date_counts)} 天")
    console.print(f"日均决策次数: {date_counts.mean():.1f}")

    hour_counts = df["hour"].value_counts().sort_index()
    t6 = Table(title="每小时决策分布")
    t6.add_column("小时", style="cyan")
    t6.add_column("次数", style="yellow", justify="right")
    for hour, count in hour_counts.items():
        t6.add_row(f"{hour:02d}:00", str(count))
    console.print(t6)


def analyze_positions(positions: dict) -> None:
    """分析当前持仓."""
    if not positions:
        console.print("[yellow]当前无持仓")
        return

    console.rule("[bold cyan]六、当前持仓分析")

    t = Table(title="当前管理持仓")
    t.add_column("合约", style="cyan")
    t.add_column("方向", style="bold")
    t.add_column("入场价", style="white", justify="right")
    t.add_column("手数", style="yellow", justify="right")
    t.add_column("ATR", style="white", justify="right")
    t.add_column("止损价", style="red", justify="right")
    t.add_column("止盈价", style="green", justify="right")
    t.add_column("持仓最高", justify="right")
    t.add_column("持仓最低", justify="right")
    t.add_column("开仓时间", style="dim")

    for sym, pos in positions.items():
        direction = pos["direction"]
        dir_style = "[red]SHORT[/red]" if direction == "SHORT" else "[green]LONG[/green]"
        t.add_row(
            sym, dir_style,
            f"{pos['entry_price']:.1f}",
            str(pos["lots"]),
            f"{pos['atr']:.2f}",
            f"{pos['stop_loss']:.1f}",
            f"{pos['take_profit']:.1f}",
            f"{pos['highest_since_entry']:.1f}",
            f"{pos['lowest_since_entry']:.0f}",
            pos["opened_at"][:19],
        )
    console.print(t)


def print_strategy_summary(config: dict) -> None:
    """输出策略架构总结."""
    console.rule("[bold magenta]量化交易策略完整总结")

    # 策略架构
    tree = Tree("[bold]策略架构")

    data_branch = tree.add("[cyan]数据层")
    data_branch.add("实时行情: 天勤量化 TqSdk (tick 级)")
    data_branch.add("日线数据: akshare / Sina Finance")
    data_branch.add("新闻数据: akshare 期货新闻")

    analysis_branch = tree.add("[cyan]分析层")
    tech_branch = analysis_branch.add("技术指标分析")
    tech_branch.add("RSI(6) — 短线超买超卖判定")
    tech_branch.add("RSI(14) — 中期超买超卖评分 [-1, 1]")
    tech_branch.add("MACD(12, 26, 9) — 动能与金叉/死叉检测")
    tech_branch.add("MA5/MA10/MA20/MA60 — 均线系统趋势判断")
    tech_branch.add("布林带(20, 2) — 波动率通道")
    tech_branch.add("ATR(14) — 15分钟K线真实波幅 (风控核心)")

    ai_branch = analysis_branch.add("AI 分析 (DeepSeek)")
    ai_branch.add("新闻舆情评分 [-1, 1]")
    ai_branch.add("技术面解读")
    ai_branch.add("供需/政策/产业链分析")
    ai_branch.add("具体进场价/止损位/止盈目标")

    sentiment_branch = analysis_branch.add("情感分析")
    sentiment_branch.add("英文: ProsusAI/FinBERT")
    sentiment_branch.add("中文: RoBERTa-ChinaNews")

    signal_branch = tree.add("[cyan]信号层")
    signal_branch.add("综合评分 = 舆情×W_s + 技术×W_t + 新闻量×W_v")
    signal_branch.add("> 0.6 → STRONG_BUY | 0.3~0.6 → BUY")
    signal_branch.add("-0.3~0.3 → HOLD | < -0.6 → STRONG_SELL")

    risk_branch = tree.add("[cyan]风控层 (ATR 体系)")
    risk_branch.add("止损 = 入场价 ∓ 1.5 × ATR(14)")
    risk_branch.add("止盈 = 入场价 ± 3.0 × ATR (2:1 风险回报比)")
    risk_branch.add("跟踪止盈: 价格每+0.5 ATR, 止损跟进+0.25 ATR")
    risk_branch.add("最大手数: 1手 | 最大持仓: 3个合约")
    risk_branch.add("信号阈值: composite_score >= 0.2~0.3")

    exec_branch = tree.add("[cyan]执行层")
    exec_branch.add("交易接口: 天勤量化 TqSdk (实盘)")
    exec_branch.add("经纪商: 国信期货")
    exec_branch.add("分析间隔: 300秒 (5分钟/轮)")
    exec_branch.add("交易时段: 09:00-11:30, 13:30-15:00, 21:00-02:30")

    console.print(tree)

    # 策略参数表
    fs = config.get("futures_strategy", {})
    console.print()
    t = Table(title="策略权重参数")
    t.add_column("参数", style="cyan")
    t.add_column("期货策略", style="green", justify="right")
    t.add_column("股票策略", style="yellow", justify="right")
    stk = config.get("strategy", {})
    t.add_row("舆情权重 (sentiment_weight)", f"{fs.get('sentiment_weight', 0):.4f}", f"{stk.get('sentiment_weight', 0):.4f}")
    t.add_row("技术权重 (technical_weight)", f"{fs.get('technical_weight', 0):.4f}", f"{stk.get('technical_weight', 0):.4f}")
    t.add_row("新闻量权重 (volume_weight)", f"{fs.get('volume_weight', 0):.4f}", f"{stk.get('volume_weight', 0):.4f}")
    t.add_row("最大仓位 (max_position)", f"{fs.get('max_position', 0):.1%}", f"{stk.get('max_position', 0):.1%}")
    t.add_row("止损线 (stop_loss)", f"{fs.get('stop_loss', 0):.1%}", f"{stk.get('stop_loss', 0):.1%}")
    t.add_row("新闻回看天数", str(fs.get("news_lookback_days", 0)), str(stk.get("news_lookback_days", 0)))
    console.print(t)

    # 口诀规则
    console.print()
    panel_text = (
        "[bold]技术指标口诀规则:[/bold]\n\n"
        "1. RSI(6) 破 30 + MACD 金叉 → [green]短线做多[/green]\n"
        "2. RSI(6) 破 70 + MACD 死叉 → [red]短线做空[/red]\n"
        "3. MACD 在零轴上方金叉 → [green]大胆做多[/green]\n"
        "4. MACD 在零轴下方金叉 → [yellow]谨慎观望[/yellow]\n"
        "5. RSI(6) 在 30-70 且无交叉 → [dim]震荡区间不操作[/dim]\n\n"
        "[bold]期货技术评分公式:[/bold]\n"
        "  composite = RSI评分×0.2 + MACD评分×0.4 + 均线评分×0.4\n\n"
        "[bold]股票技术评分公式:[/bold]\n"
        "  composite = RSI评分×0.3 + MACD评分×0.4 + 均线评分×0.3"
    )
    console.print(Panel(panel_text, title="技术指标策略规则", border_style="blue"))

    # 手续费
    console.print()
    t2 = Table(title="手续费结构")
    t2.add_column("市场", style="cyan")
    t2.add_column("费率/规则", style="green")
    t2.add_row("期货", "万分之一 (双边)")
    t2.add_row("A 股", "佣金万2.5 (最低5元) + 印花税0.05% (仅卖) + 过户费0.001%")
    t2.add_row("美股", "零佣金")
    console.print(t2)

    # 交易品种
    console.print()
    wl = config.get("watchlist", {})
    t3 = Table(title="当前监控品种")
    t3.add_column("类别", style="cyan")
    t3.add_column("品种列表", style="green")
    t3.add_row("期货合约", ", ".join(wl.get("futures_contracts", [])))
    t3.add_row("A 股", ", ".join(wl.get("cn_stocks", [])))
    t3.add_row("美股", ", ".join(wl.get("us_stocks", [])) or "无")
    console.print(t3)


def main():
    console.print(Panel.fit(
        "[bold magenta]期货量化交易策略深度分析[/bold magenta]",
        subtitle="数据来源: auto_decisions.json / auto_positions.json / config.yaml",
    ))
    console.print()

    decisions = load_decisions()
    positions = load_positions()
    config = load_config()

    print_strategy_summary(config)
    console.print()
    analyze_decisions(decisions)
    analyze_positions(positions)

    console.print()
    console.rule("[bold green]分析完成")


if __name__ == "__main__":
    main()
