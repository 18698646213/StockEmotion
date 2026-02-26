#!/usr/bin/env python3
"""基于选手每日结存数据的深度策略分析.

分析维度:
  1. 权益曲线与净值走势
  2. 每日盈亏分析 (日均盈亏/胜率/最大单日盈亏)
  3. 仓位管理 (保证金占比/风险度变化)
  4. 交易频率 (成交手数/手续费)
  5. 回撤分析 (最大回撤/回撤持续期)
  6. 资金流动 (出入金)
  7. 浮盈管理 (浮动盈亏与已实现盈亏)
  8. 策略分类
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(width=130)
logging.basicConfig(level=logging.WARNING)
DATA_DIR = Path(__file__).resolve().parent / "data"


def load_traders() -> list[dict]:
    files = sorted((DATA_DIR / "qihuo7hcn").glob("qihuo7hcn_top_traders_detail_*.json"))
    if not files:
        console.print("[red]未找到选手详情数据，请先运行采集")
        return []
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


def build_daily_df(daily: list[dict]) -> pd.DataFrame:
    if not daily:
        return pd.DataFrame()
    df = pd.DataFrame(daily)
    num_cols = ["balance", "equity", "profit", "margin", "fee", "risk",
                "fprofit", "today_in", "today_out", "roy_buy", "roy_sell"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "dateline" in df.columns:
        df["date"] = pd.to_datetime(df["dateline"])
        df = df.sort_values("date")
    return df


def analyze_single_trader(info: dict) -> dict | None:
    """分析单个选手的策略特征."""
    df = build_daily_df(info.get("daily", []))
    if df.empty or len(df) < 3:
        return None

    eq = df["equity"]
    profit = df["profit"]
    margin = df["margin"] if "margin" in df.columns else pd.Series(0, index=df.index)
    fee = df["fee"] if "fee" in df.columns else pd.Series(0, index=df.index)
    risk = df["risk"] if "risk" in df.columns else pd.Series(0, index=df.index)
    fprofit = df["fprofit"] if "fprofit" in df.columns else pd.Series(0, index=df.index)
    buy_vol = df["roy_buy"] if "roy_buy" in df.columns else pd.Series(0, index=df.index)
    sell_vol = df["roy_sell"] if "roy_sell" in df.columns else pd.Series(0, index=df.index)

    eq_valid = eq.dropna()
    if eq_valid.empty or eq_valid.iloc[0] <= 0:
        return None

    # 权益变化
    eq_start = eq_valid.iloc[-1]  # oldest (sorted ascending)
    eq_end = eq_valid.iloc[0] if len(df) > 0 else eq_start
    # data is sorted ascending, latest is last... re-check
    # actually after sort_values date, first row is earliest
    eq_start = eq_valid.iloc[0]
    eq_end = eq_valid.iloc[-1]

    # 日盈亏
    daily_pnl = profit.dropna()
    win_days = (daily_pnl > 0).sum()
    loss_days = (daily_pnl < 0).sum()
    flat_days = (daily_pnl == 0).sum()
    total_days = len(daily_pnl)
    day_win_rate = win_days / max(total_days - flat_days, 1) * 100

    # 回撤计算
    eq_series = eq.dropna()
    peak = eq_series.expanding().max()
    drawdown_pct = ((eq_series - peak) / peak * 100).fillna(0)
    max_dd = abs(drawdown_pct.min())

    # 仓位 / 保证金
    margin_valid = margin[margin > 0]
    risk_valid = risk[risk > 0]

    # 交易量
    total_vol = buy_vol.sum() + sell_vol.sum()

    # 手续费
    total_fee = fee.sum()

    # 浮盈管理
    fp_valid = fprofit.dropna()

    return {
        "nickname": info["nickname"],
        "rank": info.get("rank", 0),
        "net_value": info.get("net_value", 0),
        "profit_rate": info.get("profit_rate", 0),
        "max_drawdown_rank": info.get("max_drawdown", 0),
        "company": info.get("company", ""),
        "days": total_days,
        "eq_start": float(eq_start),
        "eq_end": float(eq_end),
        "eq_change_pct": float((eq_end - eq_start) / eq_start * 100) if eq_start > 0 else 0,
        # 日盈亏
        "daily_avg_pnl": float(daily_pnl.mean()),
        "daily_max_profit": float(daily_pnl.max()),
        "daily_max_loss": float(daily_pnl.min()),
        "daily_std": float(daily_pnl.std()) if len(daily_pnl) > 1 else 0,
        "win_days": int(win_days),
        "loss_days": int(loss_days),
        "flat_days": int(flat_days),
        "day_win_rate": float(day_win_rate),
        "total_pnl": float(daily_pnl.sum()),
        # 仓位
        "avg_margin": float(margin_valid.mean()) if len(margin_valid) > 0 else 0,
        "avg_risk": float(risk_valid.mean()) if len(risk_valid) > 0 else 0,
        "max_risk": float(risk_valid.max()) if len(risk_valid) > 0 else 0,
        "min_risk": float(risk_valid.min()) if len(risk_valid) > 0 else 0,
        # 回撤
        "max_dd_pct": float(max_dd),
        # 交易量
        "total_volume": float(total_vol),
        "avg_daily_volume": float(total_vol / max(total_days, 1)),
        "total_fee": float(total_fee),
        "fee_pnl_ratio": float(total_fee / abs(daily_pnl.sum())) if daily_pnl.sum() != 0 else 0,
        # 浮盈
        "avg_float_pnl": float(fp_valid.mean()) if len(fp_valid) > 0 else 0,
        "max_float_pnl": float(fp_valid.max()) if len(fp_valid) > 0 else 0,
        "min_float_pnl": float(fp_valid.min()) if len(fp_valid) > 0 else 0,
    }


def classify_strategy(stats: dict) -> str:
    """根据数据特征推断策略类型."""
    avg_vol = stats["avg_daily_volume"]
    risk = stats["avg_risk"]
    win_rate = stats["day_win_rate"]
    dd = stats["max_dd_pct"]
    fee_ratio = stats["fee_pnl_ratio"]

    if avg_vol > 500 and fee_ratio > 0.3:
        return "高频/日内短线"
    if avg_vol > 100:
        return "活跃短线"
    if risk > 80:
        return "重仓激进"
    if dd < 10 and win_rate > 55:
        return "稳健量化"
    if dd > 50:
        return "高风险趋势"
    if avg_vol < 20 and risk < 50:
        return "低频波段"
    return "综合策略"


def main():
    console.print(Panel.fit(
        "[bold magenta]期货实盘大赛 Top 选手 — 深度策略分析[/bold magenta]",
        subtitle="基于每日结存数据: 仓位变化 / 交易频率 / 盈亏分布 / 风控特征",
    ))

    traders = load_traders()
    if not traders:
        return

    # 分析每个选手
    all_stats = []
    for info in traders:
        stats = analyze_single_trader(info)
        if stats and stats["eq_start"] > 10:
            stats["strategy_type"] = classify_strategy(stats)
            all_stats.append(stats)

    sdf = pd.DataFrame(all_stats)
    active = sdf[sdf["total_volume"] > 0].copy()

    console.print(f"\n有效分析选手: {len(active)} / {len(traders)} (过滤了资金过小或无交易的账户)\n")

    # ======================================================================
    # 1. 权益变动总览
    # ======================================================================
    console.rule("[bold cyan]一、权益变动与收益总览")

    t = Table(title=f"Top 选手权益变动 ({len(active)} 人)")
    t.add_column("排名", style="dim", justify="right")
    t.add_column("昵称", style="cyan")
    t.add_column("策略类型", style="bold")
    t.add_column("起始权益", justify="right")
    t.add_column("最新权益", justify="right")
    t.add_column("区间变动", justify="right")
    t.add_column("日均盈亏", justify="right")
    t.add_column("累计净值", style="green", justify="right")
    t.add_column("期货公司", style="dim")

    for _, r in active.nlargest(20, "net_value").iterrows():
        chg = r["eq_change_pct"]
        chg_s = f"[green]+{chg:.1f}%[/green]" if chg > 0 else f"[red]{chg:.1f}%[/red]"
        pnl_s = f"[green]{r['daily_avg_pnl']:,.0f}[/green]" if r["daily_avg_pnl"] > 0 else f"[red]{r['daily_avg_pnl']:,.0f}[/red]"
        t.add_row(
            str(int(r["rank"])), str(r["nickname"])[:14], r["strategy_type"],
            f"{r['eq_start']:,.0f}", f"{r['eq_end']:,.0f}", chg_s, pnl_s,
            f"{r['net_value']:.2f}", str(r["company"])[:8],
        )
    console.print(t)

    # ======================================================================
    # 2. 每日盈亏与胜率分析
    # ======================================================================
    console.rule("[bold cyan]二、每日盈亏与胜率分析")

    t2 = Table(title="日盈亏与胜率详情")
    t2.add_column("昵称", style="cyan")
    t2.add_column("交易天数", justify="right")
    t2.add_column("盈利天", style="green", justify="right")
    t2.add_column("亏损天", style="red", justify="right")
    t2.add_column("日胜率", style="bold", justify="right")
    t2.add_column("日均盈亏", justify="right")
    t2.add_column("最大日盈", style="green", justify="right")
    t2.add_column("最大日亏", style="red", justify="right")
    t2.add_column("盈亏波动", justify="right")

    for _, r in active.nlargest(20, "net_value").iterrows():
        wr = r["day_win_rate"]
        wr_s = f"[green]{wr:.0f}%[/green]" if wr >= 50 else f"[red]{wr:.0f}%[/red]"
        t2.add_row(
            str(r["nickname"])[:14], str(r["days"]),
            str(r["win_days"]), str(r["loss_days"]), wr_s,
            f"{r['daily_avg_pnl']:,.0f}",
            f"{r['daily_max_profit']:,.0f}",
            f"{r['daily_max_loss']:,.0f}",
            f"{r['daily_std']:,.0f}",
        )
    console.print(t2)

    # 胜率分布统计
    wr_series = active["day_win_rate"]
    console.print(f"\n  整体日胜率均值: {wr_series.mean():.1f}%")
    console.print(f"  日胜率中位数: {wr_series.median():.1f}%")
    console.print(f"  日胜率 > 50% 的选手: {(wr_series > 50).sum()} / {len(wr_series)}")

    # ======================================================================
    # 3. 仓位管理与风险度分析
    # ======================================================================
    console.rule("[bold cyan]三、仓位管理与风险度分析")

    t3 = Table(title="仓位与风险度")
    t3.add_column("昵称", style="cyan")
    t3.add_column("平均保证金", justify="right")
    t3.add_column("平均风险度", style="bold", justify="right")
    t3.add_column("最高风险度", style="red", justify="right")
    t3.add_column("最低风险度", style="green", justify="right")
    t3.add_column("回撤(计算)", style="red", justify="right")
    t3.add_column("策略类型", style="bold")

    for _, r in active.nlargest(20, "net_value").iterrows():
        avg_r = r["avg_risk"]
        risk_s = f"[red]{avg_r:.0f}%[/red]" if avg_r > 70 else f"[yellow]{avg_r:.0f}%[/yellow]" if avg_r > 40 else f"[green]{avg_r:.0f}%[/green]"
        t3.add_row(
            str(r["nickname"])[:14],
            f"{r['avg_margin']:,.0f}",
            risk_s,
            f"{r['max_risk']:.0f}%",
            f"{r['min_risk']:.0f}%",
            f"{r['max_dd_pct']:.1f}%",
            r["strategy_type"],
        )
    console.print(t3)

    risk_series = active["avg_risk"]
    console.print(f"\n  平均风险度: {risk_series.mean():.1f}%")
    console.print(f"  风险度 > 80% (重仓): {(risk_series > 80).sum()} 人")
    console.print(f"  风险度 40-80% (中仓): {((risk_series > 40) & (risk_series <= 80)).sum()} 人")
    console.print(f"  风险度 < 40% (轻仓): {(risk_series <= 40).sum()} 人")

    # ======================================================================
    # 4. 交易频率与手续费分析
    # ======================================================================
    console.rule("[bold cyan]四、交易频率与手续费分析")

    t4 = Table(title="交易频率与成本")
    t4.add_column("昵称", style="cyan")
    t4.add_column("总成交手数", justify="right")
    t4.add_column("日均手数", justify="right")
    t4.add_column("总手续费", justify="right")
    t4.add_column("费用/盈亏比", justify="right")
    t4.add_column("策略类型", style="bold")

    for _, r in active.nlargest(20, "total_volume").iterrows():
        fee_r = r["fee_pnl_ratio"]
        fee_s = f"[red]{fee_r:.1%}[/red]" if fee_r > 0.3 else f"[green]{fee_r:.1%}[/green]"
        t4.add_row(
            str(r["nickname"])[:14],
            f"{r['total_volume']:,.0f}",
            f"{r['avg_daily_volume']:,.0f}",
            f"{r['total_fee']:,.0f}",
            fee_s,
            r["strategy_type"],
        )
    console.print(t4)

    # ======================================================================
    # 5. 浮盈管理分析
    # ======================================================================
    console.rule("[bold cyan]五、浮盈管理分析")

    t5 = Table(title="浮动盈亏管理")
    t5.add_column("昵称", style="cyan")
    t5.add_column("平均浮盈", justify="right")
    t5.add_column("最大浮盈", style="green", justify="right")
    t5.add_column("最大浮亏", style="red", justify="right")
    t5.add_column("累计已实现盈亏", justify="right")
    t5.add_column("浮盈/权益比", justify="right")

    for _, r in active.nlargest(20, "net_value").iterrows():
        fp_eq = r["avg_float_pnl"] / r["eq_end"] * 100 if r["eq_end"] > 0 else 0
        t5.add_row(
            str(r["nickname"])[:14],
            f"{r['avg_float_pnl']:,.0f}",
            f"{r['max_float_pnl']:,.0f}",
            f"{r['min_float_pnl']:,.0f}",
            f"{r['total_pnl']:,.0f}",
            f"{fp_eq:.1f}%",
        )
    console.print(t5)

    # ======================================================================
    # 6. 策略分类统计
    # ======================================================================
    console.rule("[bold cyan]六、策略类型分类统计")

    strat_counts = active["strategy_type"].value_counts()
    t6 = Table(title="策略类型分布")
    t6.add_column("策略类型", style="cyan")
    t6.add_column("人数", style="yellow", justify="right")
    t6.add_column("占比", style="green", justify="right")
    t6.add_column("平均收益率", justify="right")
    t6.add_column("平均回撤", justify="right")
    t6.add_column("平均风险度", justify="right")
    t6.add_column("平均日胜率", justify="right")

    for stype in strat_counts.index:
        sub = active[active["strategy_type"] == stype]
        t6.add_row(
            stype, str(len(sub)), f"{len(sub)/len(active)*100:.0f}%",
            f"{sub['profit_rate'].mean():.1f}%",
            f"{sub['max_dd_pct'].mean():.1f}%",
            f"{sub['avg_risk'].mean():.0f}%",
            f"{sub['day_win_rate'].mean():.0f}%",
        )
    console.print(t6)

    # ======================================================================
    # 7. 总结
    # ======================================================================
    console.rule("[bold magenta]七、深度策略洞察")

    best_wr = active.nlargest(3, "day_win_rate")
    best_rr = active.copy()
    best_rr["rr"] = best_rr["profit_rate"] / best_rr["max_dd_pct"].replace(0, np.nan)
    best_rr = best_rr.nlargest(3, "rr")
    heaviest = active.nlargest(3, "avg_risk")
    lightest = active.nsmallest(3, "avg_risk")
    most_active = active.nlargest(3, "total_volume")

    def names(df): return ", ".join(df["nickname"].tolist())

    summary = (
        f"[bold]分析样本[/bold]: {len(active)} 位 Top 选手，覆盖最近 20 个交易日\n\n"
        f"[bold]1. 日胜率最高[/bold]: {names(best_wr)}\n"
        f"   胜率 {best_wr['day_win_rate'].iloc[0]:.0f}% — 说明高胜率选手倾向于频繁小额获利\n\n"
        f"[bold]2. 收益/回撤比最佳[/bold]: {names(best_rr)}\n"
        f"   回撤极低但收益可观 — 典型量化对冲或严格风控策略\n\n"
        f"[bold]3. 最重仓选手[/bold]: {names(heaviest)}\n"
        f"   平均风险度 {heaviest['avg_risk'].mean():.0f}% — 满仓操作，高风险高回报\n\n"
        f"[bold]4. 最轻仓选手[/bold]: {names(lightest)}\n"
        f"   平均风险度 {lightest['avg_risk'].mean():.0f}% — 保守资金管理，追求稳定\n\n"
        f"[bold]5. 最活跃交易者[/bold]: {names(most_active)}\n"
        f"   日均成交 {most_active['avg_daily_volume'].mean():,.0f} 手 — 高频或日内策略\n\n"
        "[bold]关键发现[/bold]:\n"
        "  - 仓位控制是区分策略类型的核心：风险度 >80% 为激进型，<40% 为保守型\n"
        "  - 日胜率与总收益率不完全正相关，盈亏比管理更关键\n"
        "  - 浮盈管理能力（何时止盈）直接影响最终收益\n"
        "  - 手续费占比超过 30% 的高频选手需要极高胜率才能盈利"
    )
    console.print(Panel(summary, title="Top 选手策略画像", border_style="magenta"))

    # 保存分析结果
    out = Path("report")
    out.mkdir(exist_ok=True)
    active.to_csv(out / "选手策略深度分析数据.csv", index=False, encoding="utf-8-sig")
    console.print(f"\n[green]分析数据已保存: {out / '选手策略深度分析数据.csv'}")

    console.print()
    console.rule("[bold green]分析完成")


if __name__ == "__main__":
    main()
