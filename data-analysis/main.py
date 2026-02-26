#!/usr/bin/env python3
"""期货实盘交易大赛数据分析 CLI.

Usage:
    python main.py scrape --source niumoney --period year_2026
    python main.py scrape --source 7hcn --period 2025-2026
    python main.py scrape --source all
    python main.py analyze --type ranking [--source niumoney]
    python main.py analyze --type performance [--source qihuo7hcn]
    python main.py visualize --type dashboard [--source niumoney]
    python main.py visualize --type all --output report.html
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

from analysis import RankingAnalyzer, PerformanceAnalyzer
from scrapers import NiumoneyScraper, Qihuo7hcnScraper, QhrbScraper
from scrapers.niumoney import RANKING_TIDS
from scrapers.qihuo7hcn import TID_MAP
from storage import StorageManager
from visualization import CompetitionCharts

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")


def cmd_scrape(args: argparse.Namespace) -> None:
    storage = StorageManager()
    sources = [args.source] if args.source != "all" else ["niumoney", "7hcn", "qhrb"]
    max_pages = args.max_pages

    for src in sources:
        console.rule(f"[bold blue]采集: {src}")
        try:
            if src == "niumoney":
                scraper = NiumoneyScraper()
                period = args.period or "year_2026"
                tid = RANKING_TIDS.get(period, 143)
                rows = scraper.scrape_ranking(tid=tid, max_pages=max_pages)
                path = storage.save_rows(rows, "niumoney", period)
                console.print(f"[green]✓ 保存 {len(rows)} 条 -> {path}")

            elif src == "7hcn":
                scraper = Qihuo7hcnScraper()
                period = args.period or "2025-2026"
                rows = scraper.scrape_ranking(tid=period, max_pages=max_pages)
                path = storage.save_rows(rows, "qihuo7hcn", period)
                console.print(f"[green]✓ 保存 {len(rows)} 条 -> {path}")

                if args.varieties:
                    for code in args.varieties.split(","):
                        code = code.strip().upper()
                        v_rows = scraper.scrape_futures_ranking(code, max_pages=max_pages)
                        path = storage.save_rows(v_rows, "qihuo7hcn", f"futures_{code}")
                        console.print(f"[green]✓ {code}: {len(v_rows)} 条 -> {path}")

            elif src == "qhrb":
                scraper = QhrbScraper()
                edition = int(args.edition or 12)
                for group in ("light", "heavy"):
                    rows = scraper.scrape_ranking(edition=edition, group=group, max_pages=max_pages)
                    path = storage.save_rows(rows, "qhrb", f"sp{edition}_{group}")
                    console.print(f"[green]✓ {group}: {len(rows)} 条 -> {path}")

        except Exception as e:
            console.print(f"[red]✗ {src} 采集失败: {e}")


def cmd_analyze(args: argparse.Namespace) -> None:
    storage = StorageManager()
    source = args.source or "niumoney"
    df = storage.load_all(source)
    if df.empty:
        console.print(f"[yellow]没有 {source} 的数据，请先运行 scrape")
        return

    console.rule(f"[bold blue]分析: {source} ({len(df)} 条)")

    if args.type in ("ranking", "all"):
        ra = RankingAnalyzer(df)
        summary = ra.summary()
        t = Table(title="排行榜概况")
        t.add_column("指标", style="cyan")
        t.add_column("值", style="green")
        for k, v in summary.items():
            t.add_row(k, f"{v:.4f}" if isinstance(v, float) else str(v))
        console.print(t)

        dist = ra.return_distribution()
        if dist:
            t2 = Table(title="收益率分布")
            t2.add_column("统计量", style="cyan")
            t2.add_column("值", style="green")
            for k, v in dist.items():
                t2.add_row(k, f"{v:.4f}" if isinstance(v, float) else str(v))
            console.print(t2)

        pl = ra.profit_loss_analysis()
        if pl:
            t3 = Table(title="盈亏分析")
            t3.add_column("指标", style="cyan")
            t3.add_column("值", style="green")
            for k, v in pl.items():
                t3.add_row(k, f"{v:.4f}" if isinstance(v, float) else str(v))
            console.print(t3)

    if args.type in ("performance", "all"):
        pa = PerformanceAnalyzer(df)
        stats = pa.return_statistics()
        if stats:
            t = Table(title="选手表现统计")
            t.add_column("指标", style="cyan")
            t.add_column("值", style="green")
            for k, v in stats.items():
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        t.add_row(f"  {kk}", f"{vv:.4f}")
                else:
                    t.add_row(k, f"{v:.4f}" if isinstance(v, float) else str(v))
            console.print(t)

        dd = pa.drawdown_analysis()
        if dd:
            t2 = Table(title="回撤分析")
            t2.add_column("指标", style="cyan")
            t2.add_column("值", style="green")
            for k, v in dd.items():
                t2.add_row(k, f"{v:.4f}" if isinstance(v, float) else str(v))
            console.print(t2)

        top = pa.top_performers(10)
        if not top.empty:
            console.print("\n[bold]Top 10 风险收益比:")
            console.print(top.to_string())


def cmd_visualize(args: argparse.Namespace) -> None:
    storage = StorageManager()
    source = args.source or "niumoney"
    df = storage.load_all(source)
    if df.empty:
        console.print(f"[yellow]没有 {source} 的数据，请先运行 scrape")
        return

    console.rule(f"[bold blue]可视化: {source} ({len(df)} 条)")
    charts = CompetitionCharts()
    output_dir = Path(args.output) if args.output else Path("output")
    output_dir.mkdir(exist_ok=True)

    figs = {}
    if args.type in ("distribution", "all"):
        figs["return_distribution"] = charts.return_distribution(df)
    if args.type in ("scatter", "all"):
        figs["risk_return_scatter"] = charts.risk_return_scatter(df)
    if args.type in ("pie", "all"):
        figs["equity_pie"] = charts.equity_pie(df)
    if args.type in ("dashboard", "all"):
        figs["dashboard"] = charts.dashboard(df)
    if args.type in ("company", "all") and "company" in df.columns:
        ra = RankingAnalyzer(df)
        company_df = ra.company_stats()
        if not company_df.empty:
            figs["company_bar"] = charts.company_bar(company_df)

    for name, fig in figs.items():
        html_path = output_dir / f"{name}.html"
        fig.write_html(str(html_path))
        console.print(f"[green]✓ {html_path}")

    console.print(f"\n[bold green]共生成 {len(figs)} 个图表 -> {output_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="期货实盘交易大赛数据分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # scrape
    p_scrape = sub.add_parser("scrape", help="采集排行榜数据")
    p_scrape.add_argument("--source", default="all", choices=["niumoney", "7hcn", "qhrb", "all"])
    p_scrape.add_argument("--period", help="榜单周期 (niumoney: year_2026; 7hcn: 2025-2026)")
    p_scrape.add_argument("--max-pages", type=int, default=None, help="最大页数")
    p_scrape.add_argument("--varieties", help="品种代码,逗号分隔 (7hcn only, e.g. AU,CU,RB)")
    p_scrape.add_argument("--edition", default="12", help="期货日报大赛届数 (qhrb only)")

    # analyze
    p_analyze = sub.add_parser("analyze", help="数据分析")
    p_analyze.add_argument("--type", default="all", choices=["ranking", "performance", "all"])
    p_analyze.add_argument("--source", default="niumoney", choices=["niumoney", "qihuo7hcn", "qhrb"])

    # visualize
    p_viz = sub.add_parser("visualize", help="数据可视化")
    p_viz.add_argument("--type", default="all",
                       choices=["distribution", "scatter", "pie", "company", "dashboard", "all"])
    p_viz.add_argument("--source", default="niumoney", choices=["niumoney", "qihuo7hcn", "qhrb"])
    p_viz.add_argument("--output", default="output", help="输出目录")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "scrape":
        cmd_scrape(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "visualize":
        cmd_visualize(args)


if __name__ == "__main__":
    main()
