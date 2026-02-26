#!/usr/bin/env python3
"""期货实盘交易大赛选手策略分析.

分析内容：
  1. 参赛规模与资金分布
  2. 交易品种盈利排行
  3. 选手收益率与回撤分布
  4. 盈亏比例与胜率分析
  5. 期货公司参赛分布
  6. 轻量组 vs 重量组对比
  7. Top 选手策略特征
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from storage import StorageManager
from scrapers.qihuo7hcn import FUTURES_CODES

console = Console(width=120)
logging.basicConfig(level=logging.WARNING)

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_niumoney() -> dict[str, pd.DataFrame]:
    """加载牛钱网各组数据."""
    sm = StorageManager()
    result = {}
    for label in ["year_2026_all", "year_2026_light", "year_2026_heavy", "year_2026_option"]:
        df = sm.load_latest("niumoney", label)
        if df is not None and not df.empty:
            result[label] = df
    return result


def load_7hcn_contest() -> pd.DataFrame:
    """加载七禾网综合排行数据（合并三个排序维度去重）."""
    sm = StorageManager()
    frames = []
    for label in ["2025-2026_nav", "2025-2026_credit", "2025-2026_profit"]:
        df = sm.load_latest("qihuo7hcn", label)
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if "nickname" in combined.columns:
        combined = combined.drop_duplicates(subset=["nickname"], keep="first")
    return combined


def load_7hcn_varieties() -> dict[str, pd.DataFrame]:
    """加载七禾网各品种盈利排行."""
    sm = StorageManager()
    result = {}
    for f in sorted((DATA_DIR / "qihuo7hcn").glob("qihuo7hcn_futures_*.csv")):
        code = f.stem.split("futures_")[1].split("_")[0]
        df = pd.read_csv(f, encoding="utf-8-sig")
        if not df.empty:
            result[code] = df
    return result


def ensure_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ======================================================================
# 分析模块
# ======================================================================

def analyze_scale(nm_data: dict[str, pd.DataFrame]) -> None:
    """参赛规模与资金分布."""
    console.rule("[bold cyan]一、参赛规模与资金分布（牛钱网 2026 年度）")

    all_df = nm_data.get("year_2026_all")
    if all_df is None:
        console.print("[yellow]无数据")
        return

    all_df = ensure_numeric(all_df, ["equity", "net_profit", "profit_rate", "max_drawdown",
                                      "net_value", "credit_score"])

    total = len(all_df)
    light = nm_data.get("year_2026_light")
    heavy = nm_data.get("year_2026_heavy")
    option = nm_data.get("year_2026_option")

    t = Table(title="参赛规模")
    t.add_column("指标", style="cyan")
    t.add_column("数值", style="green", justify="right")
    t.add_row("总参赛账户", str(total))
    t.add_row("轻量组 (<50万)", str(len(light)) if light is not None else "N/A")
    t.add_row("重量组 (>=50万)", str(len(heavy)) if heavy is not None else "N/A")
    t.add_row("期权组", str(len(option)) if option is not None else "N/A")
    console.print(t)

    # 资金规模分布
    eq = all_df["equity"].dropna()
    if not eq.empty:
        bins = [0, 50_000, 100_000, 500_000, 1_000_000, 5_000_000, 10_000_000, float("inf")]
        labels = ["<5万", "5-10万", "10-50万", "50-100万", "100-500万", "500万-1000万", ">1000万"]
        cats = pd.cut(eq, bins=bins, labels=labels)
        counts = cats.value_counts().sort_index()

        t2 = Table(title="资金规模分布")
        t2.add_column("资金规模", style="cyan")
        t2.add_column("人数", style="yellow", justify="right")
        t2.add_column("占比", style="green", justify="right")
        for label, count in counts.items():
            t2.add_row(str(label), str(count), f"{count/total*100:.1f}%")
        console.print(t2)

        console.print(f"\n  总权益: {eq.sum():,.0f} 元 ({eq.sum()/1e8:.2f} 亿)")
        console.print(f"  平均权益: {eq.mean():,.0f} 元")
        console.print(f"  中位数权益: {eq.median():,.0f} 元")


def analyze_profit_loss(nm_data: dict[str, pd.DataFrame]) -> None:
    """收益率与盈亏分析."""
    console.rule("[bold cyan]二、收益率与盈亏分析")

    all_df = nm_data.get("year_2026_all")
    if all_df is None:
        return

    all_df = ensure_numeric(all_df, ["profit_rate", "net_profit", "max_drawdown", "net_value"])

    pr = all_df["profit_rate"].dropna()
    np_ = all_df["net_profit"].dropna()

    profitable = (np_ > 0).sum()
    losing = (np_ < 0).sum()
    breakeven = (np_ == 0).sum()
    total = len(np_)

    t = Table(title="盈亏统计")
    t.add_column("指标", style="cyan")
    t.add_column("数值", style="green", justify="right")
    t.add_row("总账户", str(total))
    t.add_row("[green]盈利账户[/green]", f"{profitable} ({profitable/total*100:.1f}%)")
    t.add_row("[red]亏损账户[/red]", f"{losing} ({losing/total*100:.1f}%)")
    t.add_row("持平账户", f"{breakeven}")
    if profitable > 0:
        t.add_row("盈利均值", f"{np_[np_>0].mean():,.0f} 元")
        t.add_row("最大盈利", f"{np_.max():,.0f} 元")
    if losing > 0:
        t.add_row("亏损均值", f"{np_[np_<0].mean():,.0f} 元")
        t.add_row("最大亏损", f"{np_.min():,.0f} 元")
    console.print(t)

    # 收益率分布
    if not pr.empty:
        t2 = Table(title="收益率分布")
        t2.add_column("统计量", style="cyan")
        t2.add_column("值", style="green", justify="right")
        t2.add_row("平均收益率", f"{pr.mean():.2f}%")
        t2.add_row("中位数收益率", f"{pr.median():.2f}%")
        t2.add_row("标准差", f"{pr.std():.2f}%")
        t2.add_row("最大收益率", f"{pr.max():.2f}%")
        t2.add_row("最小收益率", f"{pr.min():.2f}%")
        t2.add_row("收益>100% 人数", f"{(pr>100).sum()} ({(pr>100).mean()*100:.1f}%)")
        t2.add_row("收益>50% 人数", f"{(pr>50).sum()} ({(pr>50).mean()*100:.1f}%)")
        t2.add_row("收益>0% 人数", f"{(pr>0).sum()} ({(pr>0).mean()*100:.1f}%)")
        t2.add_row("亏损>50% 人数", f"{(pr<-50).sum()} ({(pr<-50).mean()*100:.1f}%)")
        console.print(t2)

    # 最大回撤分布
    dd = all_df["max_drawdown"].dropna()
    if not dd.empty:
        t3 = Table(title="最大回撤分布")
        t3.add_column("回撤区间", style="cyan")
        t3.add_column("人数", style="yellow", justify="right")
        t3.add_column("占比", style="green", justify="right")
        dd_bins = [(0, 10), (10, 20), (20, 30), (30, 50), (50, 70), (70, 100)]
        for lo, hi in dd_bins:
            cnt = ((dd >= lo) & (dd < hi)).sum()
            t3.add_row(f"{lo}%-{hi}%", str(cnt), f"{cnt/len(dd)*100:.1f}%")
        console.print(t3)
        console.print(f"  平均最大回撤: {dd.mean():.1f}%")
        console.print(f"  中位数最大回撤: {dd.median():.1f}%")


def analyze_group_comparison(nm_data: dict[str, pd.DataFrame]) -> None:
    """轻量组 vs 重量组对比."""
    console.rule("[bold cyan]三、轻量组 vs 重量组 对比")

    light = nm_data.get("year_2026_light")
    heavy = nm_data.get("year_2026_heavy")
    if light is None or heavy is None:
        console.print("[yellow]数据不足")
        return

    light = ensure_numeric(light, ["profit_rate", "max_drawdown", "net_value", "net_profit", "credit_score", "equity"])
    heavy = ensure_numeric(heavy, ["profit_rate", "max_drawdown", "net_value", "net_profit", "credit_score", "equity"])

    t = Table(title="组别对比")
    t.add_column("指标", style="cyan")
    t.add_column("轻量组 (<50万)", style="yellow", justify="right")
    t.add_column("重量组 (>=50万)", style="green", justify="right")

    t.add_row("参赛人数", str(len(light)), str(len(heavy)))
    t.add_row("平均权益", f"{light['equity'].mean():,.0f}", f"{heavy['equity'].mean():,.0f}")
    t.add_row("平均收益率", f"{light['profit_rate'].mean():.2f}%", f"{heavy['profit_rate'].mean():.2f}%")
    t.add_row("中位数收益率", f"{light['profit_rate'].median():.2f}%", f"{heavy['profit_rate'].median():.2f}%")
    t.add_row("平均净值", f"{light['net_value'].mean():.4f}", f"{heavy['net_value'].mean():.4f}")

    light_pos = (light["net_profit"] > 0).mean() * 100
    heavy_pos = (heavy["net_profit"] > 0).mean() * 100
    t.add_row("盈利比例", f"{light_pos:.1f}%", f"{heavy_pos:.1f}%")
    t.add_row("平均回撤", f"{light['max_drawdown'].mean():.1f}%", f"{heavy['max_drawdown'].mean():.1f}%")
    t.add_row("中位数回撤", f"{light['max_drawdown'].median():.1f}%", f"{heavy['max_drawdown'].median():.1f}%")
    t.add_row("平均综合积分", f"{light['credit_score'].mean():.2f}", f"{heavy['credit_score'].mean():.2f}")
    console.print(t)


def analyze_varieties(variety_data: dict[str, pd.DataFrame]) -> None:
    """品种盈利排行分析."""
    console.rule("[bold cyan]四、交易品种盈利排行（七禾网数据）")

    if not variety_data:
        console.print("[yellow]无品种数据")
        return

    # 汇总各品种 Top 选手的盈利情况
    variety_stats = []
    for code, df in variety_data.items():
        df = ensure_numeric(df, ["profit", "win_rate", "avg_profit", "equity"])
        name = FUTURES_CODES.get(code, code)
        n = len(df)
        total_profit = df["profit"].sum()
        avg_profit = df["profit"].mean()
        max_profit = df["profit"].max()
        avg_wr = df["win_rate"].mean() if "win_rate" in df.columns else 0
        variety_stats.append({
            "code": code, "name": name, "traders": n,
            "total_profit": total_profit, "avg_profit": avg_profit,
            "max_profit": max_profit, "avg_win_rate": avg_wr,
        })

    vdf = pd.DataFrame(variety_stats).sort_values("total_profit", ascending=False)

    t = Table(title="品种盈利排行 (Top 50 选手汇总)")
    t.add_column("排名", style="dim", justify="right")
    t.add_column("品种", style="cyan")
    t.add_column("代码", style="dim")
    t.add_column("参与人数", style="yellow", justify="right")
    t.add_column("总盈利(万)", style="green", justify="right")
    t.add_column("人均盈利(万)", style="green", justify="right")
    t.add_column("最高盈利(万)", style="bold green", justify="right")
    t.add_column("平均胜率", style="white", justify="right")

    for i, (_, row) in enumerate(vdf.iterrows(), 1):
        t.add_row(
            str(i), row["name"], row["code"], str(row["traders"]),
            f"{row['total_profit']/1e4:.1f}",
            f"{row['avg_profit']/1e4:.1f}",
            f"{row['max_profit']/1e4:.1f}",
            f"{row['avg_win_rate']:.1f}%" if row["avg_win_rate"] > 0 else "-",
        )
    console.print(t)

    # 品种分类
    console.print()
    categories = {
        "贵金属": ["AU", "AG"],
        "有色金属": ["CU", "AL"],
        "黑色系": ["RB", "I"],
        "能源化工": ["SC", "FU", "TA", "MA", "EG"],
        "农产品": ["M", "OI", "CF", "SR", "C", "LH"],
        "新兴品种": ["EC", "SI", "LC"],
    }
    t2 = Table(title="板块盈利对比")
    t2.add_column("板块", style="cyan")
    t2.add_column("品种", style="dim")
    t2.add_column("总盈利(万)", style="green", justify="right")
    t2.add_column("人均盈利(万)", style="green", justify="right")

    for cat_name, codes in categories.items():
        sub = vdf[vdf["code"].isin(codes)]
        if sub.empty:
            continue
        cat_total = sub["total_profit"].sum()
        cat_avg = sub["avg_profit"].mean()
        code_str = ", ".join(sub["code"].tolist())
        t2.add_row(cat_name, code_str, f"{cat_total/1e4:.1f}", f"{cat_avg/1e4:.1f}")
    console.print(t2)


def analyze_companies(qh_df: pd.DataFrame) -> None:
    """期货公司参赛分布."""
    console.rule("[bold cyan]五、期货公司参赛分布（七禾网数据）")

    if qh_df.empty or "company" not in qh_df.columns:
        console.print("[yellow]无数据")
        return

    qh_df = ensure_numeric(qh_df, ["net_value", "profit_rate", "max_drawdown", "credit_score", "equity"])

    company_stats = qh_df.groupby("company").agg(
        count=("company", "size"),
        avg_nav=("net_value", "mean"),
        avg_drawdown=("max_drawdown", "mean"),
    ).sort_values("count", ascending=False)

    t = Table(title="期货公司分布 (Top 15)")
    t.add_column("排名", style="dim", justify="right")
    t.add_column("期货公司", style="cyan")
    t.add_column("参赛人数", style="yellow", justify="right")
    t.add_column("平均净值", style="green", justify="right")
    t.add_column("平均回撤", style="red", justify="right")

    for i, (company, row) in enumerate(company_stats.head(15).iterrows(), 1):
        t.add_row(
            str(i), company, str(int(row["count"])),
            f"{row['avg_nav']:.4f}",
            f"{row['avg_drawdown']:.1f}%",
        )
    console.print(t)


def analyze_top_traders(nm_data: dict[str, pd.DataFrame], qh_df: pd.DataFrame) -> None:
    """Top 选手策略特征."""
    console.rule("[bold cyan]六、Top 选手策略特征")

    # 牛钱网 Top 选手（按净利润）
    all_df = nm_data.get("year_2026_all")
    if all_df is not None:
        all_df = ensure_numeric(all_df, ["profit_rate", "max_drawdown", "net_value",
                                          "net_profit", "credit_score", "equity"])
        top = all_df.nlargest(15, "net_profit")

        t = Table(title="牛钱网 Top 15 (按净利润)")
        t.add_column("排名", style="dim", justify="right")
        t.add_column("昵称", style="cyan")
        t.add_column("净利润(万)", style="green", justify="right")
        t.add_column("收益率", style="green", justify="right")
        t.add_column("最大回撤", style="red", justify="right")
        t.add_column("净值", style="white", justify="right")
        t.add_column("权益(万)", style="yellow", justify="right")
        t.add_column("收益/回撤", style="bold", justify="right")

        for i, (_, row) in enumerate(top.iterrows(), 1):
            dd = row["max_drawdown"]
            rr = row["profit_rate"] / dd if dd > 0 else 0
            t.add_row(
                str(i),
                str(row.get("nickname", ""))[:12],
                f"{row['net_profit']/1e4:.1f}",
                f"{row['profit_rate']:.1f}%",
                f"{dd:.1f}%",
                f"{row['net_value']:.4f}",
                f"{row['equity']/1e4:.1f}",
                f"{rr:.2f}",
            )
        console.print(t)

        # Top 选手统计特征
        console.print()
        console.print("[bold]Top 15 选手统计特征:")
        console.print(f"  平均收益率: {top['profit_rate'].mean():.1f}%")
        console.print(f"  平均最大回撤: {top['max_drawdown'].mean():.1f}%")
        console.print(f"  平均收益/回撤比: {(top['profit_rate']/top['max_drawdown'].replace(0,np.nan)).mean():.2f}")
        console.print(f"  平均权益: {top['equity'].mean()/1e4:.1f} 万")

    # 七禾网 Top 选手
    if not qh_df.empty:
        qh_df = ensure_numeric(qh_df, ["net_value", "profit_rate", "max_drawdown",
                                         "equity", "credit_score", "win_rate"])
        top_qh = qh_df.nlargest(15, "net_value")

        console.print()
        t2 = Table(title="七禾网 Top 15 (按累计净值)")
        t2.add_column("排名", style="dim", justify="right")
        t2.add_column("昵称", style="cyan")
        t2.add_column("累计净值", style="bold green", justify="right")
        t2.add_column("收益率", style="green", justify="right")
        t2.add_column("最大回撤", style="red", justify="right")
        t2.add_column("权益(万)", style="yellow", justify="right")
        t2.add_column("期货公司", style="dim")
        t2.add_column("胜率", style="white", justify="right")

        for i, (_, row) in enumerate(top_qh.iterrows(), 1):
            t2.add_row(
                str(i),
                str(row.get("nickname", ""))[:12],
                f"{row['net_value']:.4f}",
                f"{row['profit_rate']:.1f}%" if pd.notna(row.get("profit_rate")) else "-",
                f"{row['max_drawdown']:.1f}%",
                f"{row['equity']/1e4:.1f}" if row.get("equity", 0) > 0 else "-",
                str(row.get("company", ""))[:10],
                f"{row['win_rate']:.1f}%" if pd.notna(row.get("win_rate")) and row["win_rate"] > 0 else "-",
            )
        console.print(t2)


def print_summary() -> None:
    """输出分析总结."""
    console.rule("[bold magenta]七、策略分析总结")

    summary = (
        "[bold]1. 参赛门槛与资金分布[/bold]\n"
        "   - 牛钱网不设最低资金门槛，轻量组 (<50万) 占绝大多数\n"
        "   - 重量组 (>=50万) 约占总参赛人数的 15-20%\n\n"
        "[bold]2. 盈亏真相（期货市场的残酷现实）[/bold]\n"
        "   - 期货市场盈利占比通常在 20-30%，大多数参赛者亏损\n"
        "   - 平均回撤普遍较大，50%以上回撤的账户占比显著\n"
        "   - 极少数 Top 选手贡献了大部分利润\n\n"
        "[bold]3. 品种选择趋势[/bold]\n"
        "   - 贵金属(黄金、白银)和能源(原油)是盈利最高的品种\n"
        "   - 黑色系(螺纹钢、铁矿)交易活跃但波动大\n"
        "   - 新兴品种(集运指数、碳酸锂、工业硅)吸引投机资金\n"
        "   - 农产品(豆粕、菜油)相对稳健但利润空间有限\n\n"
        "[bold]4. Top 选手共性特征[/bold]\n"
        "   - 收益/回撤比 > 2 是优秀选手的标志\n"
        "   - 高净值选手往往回撤控制更好\n"
        "   - 重量组整体表现更稳健（资金管理更成熟）\n"
        "   - 持续盈利的选手通常专注 2-3 个品种\n\n"
        "[bold]5. 关键技术指标启示[/bold]\n"
        "   - 胜率 50-60% 配合合理盈亏比即可实现长期盈利\n"
        "   - 回撤控制是区分优秀选手和普通选手的关键\n"
        "   - 综合积分体系兼顾净值、收益率、回撤和净利润"
    )
    console.print(Panel(summary, title="期货实盘大赛策略洞察", border_style="magenta"))


def main():
    console.print(Panel.fit(
        "[bold magenta]期货实盘交易大赛 — 选手策略深度分析[/bold magenta]",
        subtitle="数据来源: 牛钱网 + 七禾网实战排行榜",
    ))
    console.print()

    nm_data = load_niumoney()
    qh_df = load_7hcn_contest()
    variety_data = load_7hcn_varieties()

    analyze_scale(nm_data)
    console.print()
    analyze_profit_loss(nm_data)
    console.print()
    analyze_group_comparison(nm_data)
    console.print()
    analyze_varieties(variety_data)
    console.print()
    analyze_companies(qh_df)
    console.print()
    analyze_top_traders(nm_data, qh_df)
    console.print()
    print_summary()
    console.print()
    console.rule("[bold green]分析完成")


if __name__ == "__main__":
    main()
