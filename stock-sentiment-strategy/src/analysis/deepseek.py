"""DeepSeek API client for AI-powered financial analysis.

Replaces local NLP sentiment models with DeepSeek large language model.
Handles: news sentiment, technical interpretation, and investment advice
via a single unified prompt.
"""

import json
import logging
import re
from typing import Dict, List, Optional

import requests

from src.config import DeepSeekConfig
from src.data.news_us import NewsItem

logger = logging.getLogger(__name__)

_TIMEOUT = 60


def _call_deepseek(
    config: DeepSeekConfig,
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
) -> Optional[str]:
    """Call DeepSeek API (OpenAI-compatible) and return assistant content."""
    if not config.api_key:
        logger.warning("DeepSeek API key 未配置，跳过 AI 分析")
        return None

    url = f"{config.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4000,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        logger.error("DeepSeek API 请求超时 (%ds)", _TIMEOUT)
        return None
    except requests.exceptions.RequestException as e:
        logger.error("DeepSeek API 请求失败: %s", e)
        return None
    except (KeyError, IndexError) as e:
        logger.error("DeepSeek API 响应解析失败: %s", e)
        return None


def _extract_json(text: str) -> Optional[Dict]:
    """Extract JSON object from LLM response (may be wrapped in markdown)."""
    if not text:
        return None

    # Try parsing as-is first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` block
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding the first { ... } block
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    return None


def analyze_with_deepseek(
    config: DeepSeekConfig,
    ticker: str,
    market: str,
    news_items: List[NewsItem],
    technical_summary: Dict,
    swing_summary: Optional[Dict] = None,
) -> Optional[Dict]:
    """Run comprehensive AI analysis using DeepSeek.

    Sends news + technical data as context, returns structured analysis:
    - sentiment_score: float [-1, 1]
    - sentiment_label: str
    - news_summary: str (AI-generated brief)
    - technical_analysis: str
    - investment_advice: list of advice dicts
    - composite_score: float [-1, 1]
    - signal: str (STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL)
    - signal_cn: str
    """
    if not config.api_key:
        return None

    news_text = _format_news(news_items)
    tech_text = _format_technical(technical_summary)
    swing_text = _format_swing(swing_summary) if swing_summary else ""

    if market == "FUTURES":
        system_prompt = _SYSTEM_PROMPT_FUTURES
        user_prompt = _build_futures_prompt(ticker, news_text, tech_text, swing_text)
    else:
        system_prompt = _SYSTEM_PROMPT_STOCK
        user_prompt = _build_stock_prompt(ticker, market, news_text, tech_text)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    raw = _call_deepseek(config, messages)
    if not raw:
        return None

    result = _extract_json(raw)
    if not result:
        logger.warning("DeepSeek 返回无法解析为 JSON: %s...", raw[:200])
        return None

    _validate_result(result)
    return result


def _format_news(items: List[NewsItem], max_items: int = 15) -> str:
    if not items:
        return "暂无相关新闻。"
    lines = []
    for i, item in enumerate(items[:max_items], 1):
        date_str = item.published_at.strftime("%m-%d %H:%M") if item.published_at else ""
        summary = item.summary[:200] if item.summary else item.title
        lines.append(f"{i}. [{date_str}] {item.title}\n   {summary}")
    return "\n".join(lines)


def _format_technical(tech: Dict) -> str:
    lines = []
    rsi6 = tech.get("rsi6")
    if rsi6 is not None:
        lines.append(f"- RSI(6): {rsi6}（<30 超卖 / >70 超买）")
    lines.append(f"- RSI 评分: {tech.get('rsi_score', 0):.2f}（[-1,1]，正=超卖反弹信号）")
    lines.append(f"- MACD 评分: {tech.get('macd_score', 0):.2f}（[-1,1]，正=多头动能）")
    lines.append(f"- 均线趋势评分: {tech.get('ma_score', 0):.2f}（[-1,1]，正=多头排列）")
    macd_cross = tech.get("macd_cross", "none")
    if macd_cross == "golden":
        lines.append("- MACD 近期出现金叉（多头信号）")
    elif macd_cross == "death":
        lines.append("- MACD 近期出现死叉（空头信号）")
    else:
        lines.append("- MACD 无近期交叉")
    lines.append(f"- MACD 位于零轴{'上方（多头区域）' if tech.get('macd_above_zero') else '下方（空头区域）'}")
    lines.append(f"- 技术综合评分: {tech.get('composite', 0):.2f}")
    return "\n".join(lines)


def _format_swing(swing: Optional[Dict]) -> str:
    if not swing:
        return ""
    trend = swing.get("trend", "neutral")
    lines = []
    if trend == "bullish":
        lines.append("- 价格在 MA60 上方，整体趋势偏多")
    elif trend == "bearish":
        lines.append("- 价格在 MA60 下方，整体趋势偏空")
    else:
        lines.append("- 趋势不明朗")

    ma5 = swing.get("ma5")
    ma20 = swing.get("ma20")
    ma60 = swing.get("ma60")
    if ma5 is not None:
        lines.append(f"- MA5（5日均线）: {ma5}")
    if ma20 is not None:
        lines.append(f"- MA20（20日均线）: {ma20}")
    if ma60 is not None:
        lines.append(f"- MA60（60日均线）: {ma60}")

    if ma5 is not None and ma20 is not None:
        if ma5 > ma20:
            lines.append("- 短期均线排列: MA5 > MA20（短期偏多）")
        else:
            lines.append("- 短期均线排列: MA5 < MA20（短期偏空）")

    cross = swing.get("ma5_ma20_cross", "none")
    if cross == "golden":
        lines.append("- MA5/MA20 近期出现金叉（短期多头信号）")
    elif cross == "death":
        lines.append("- MA5/MA20 近期出现死叉（短期空头信号）")

    return "\n".join(lines)


_SYSTEM_PROMPT_STOCK = """你是一位资深金融分析师，专精股票市场。请根据提供的新闻资讯和技术指标数据，给出全面的分析结果。

你必须严格以 JSON 格式返回结果，不要包含任何额外文字。JSON 结构如下：
{
  "sentiment_score": 0.0,       // 整体舆情得分，范围 [-1, 1]，正=利好，负=利空
  "sentiment_label": "neutral", // "positive" / "negative" / "neutral"
  "news_summary": "",           // 一段话总结当前新闻面（50-100字）
  "news_sentiments": [          // 对每条新闻的单独分析（按输入顺序，序号从1开始）
    {
      "index": 1,               // 新闻序号（对应输入中的编号）
      "score": 0.0,             // 该条新闻的情感得分 [-1, 1]
      "label": "neutral",       // "positive" / "negative" / "neutral"
      "summary": ""             // 一句话 AI 解读该条新闻对股价的影响（20-40字）
    }
  ],
  "technical_analysis": "",     // 一段话解读技术面（50-100字）
  "investment_advice": [        // 投资建议列表
    {
      "action": "HOLD",         // "BUY" / "SELL" / "HOLD"
      "rule": "",               // 策略规则名称（简短）
      "detail": ""              // 详细说明（一句话）
    }
  ],
  "composite_score": 0.0,       // 综合评分 [-1, 1]
  "signal": "HOLD",             // "STRONG_BUY" / "BUY" / "HOLD" / "SELL" / "STRONG_SELL"
  "signal_cn": "持有"           // 中文信号
}"""

_SYSTEM_PROMPT_FUTURES = """你是一位资深中国商品期货分析师，负责提供全面的期货分析和交易建议。

你的分析需要覆盖以下方面：
1. **新闻舆情分析**：基于近期新闻判断该品种的供需面、政策面、产业链影响
2. **技术面分析**：基于均线系统（MA5/MA20/MA60）、RSI、MACD 等指标判断趋势和买卖时机
3. **综合交易建议**：结合舆情和技术面，给出明确的操作建议（做多/做空/观望），包含具体的进场价、止损位、止盈目标

分析原则：
- 顺势交易，不逆势操作
- 给出具体数字（进场价、止损价、止盈价），而非模糊建议
- 如果没有明确信号，建议观望，不要强行给出交易建议
- 风险控制：单笔亏损建议不超过总资金 4%

你必须严格以 JSON 格式返回结果，不要包含任何额外文字。JSON 结构如下：
{
  "sentiment_score": 0.0,       // 整体舆情得分 [-1, 1]，正=利多，负=利空
  "sentiment_label": "neutral", // "positive" / "negative" / "neutral"
  "news_summary": "",           // 新闻面分析（80-150字），包含供需、政策、产业链影响
  "news_sentiments": [          // 对每条新闻的单独分析（按输入顺序，序号从1开始）
    {
      "index": 1,               // 新闻序号
      "score": 0.0,             // 该条新闻的情感得分 [-1, 1]，利多为正，利空为负
      "label": "neutral",       // "positive" / "negative" / "neutral"
      "summary": ""             // 一句话 AI 解读该条新闻对该品种价格的影响（20-40字）
    }
  ],
  "technical_analysis": "",     // 技术面分析（80-150字），包含趋势判断、关键支撑阻力位
  "investment_advice": [        // 交易建议列表（1-3条）
    {
      "action": "HOLD",         // "BUY"=做多 / "SELL"=做空 / "HOLD"=观望
      "rule": "",               // 策略依据名称（简短，如"趋势突破"/"供需偏多"/"技术回调"）
      "detail": ""              // 详细操作建议，必须包含具体价位
    }
  ],
  "composite_score": 0.0,       // 综合评分 [-1, 1]，>0.3 偏多，<-0.3 偏空
  "signal": "HOLD",             // "STRONG_BUY" / "BUY" / "HOLD" / "SELL" / "STRONG_SELL"
  "signal_cn": "持有"           // 中文信号
}"""


def _build_stock_prompt(ticker: str, market: str, news: str, tech: str) -> str:
    market_name = "美股" if market == "US" else "A股"
    return f"""请分析以下{market_name}标的：{ticker}

【近期新闻】
{news}

【技术指标】
{tech}

请综合新闻面和技术面，给出你的分析结果（JSON格式）。"""


def _build_futures_prompt(ticker: str, news: str, tech: str, swing: str) -> str:
    return f"""请全面分析以下期货品种：{ticker}

【近期新闻与行业资讯】
{news}

【技术指标数据】
{tech}

【均线系统数据】
{swing if swing else "暂无均线数据"}

请基于以上数据，从舆情面和技术面两个维度进行分析，给出你的交易建议（JSON格式）。
要求：
1. 新闻摘要要分析供需关系、政策影响、产业链变化对该品种价格的影响方向
2. 技术分析要结合均线排列、RSI、MACD 判断当前趋势强度和可能的转折点
3. 交易建议必须给出具体的进场价位、止损价位和止盈目标价
4. 如果没有明确的交易机会，直接建议观望，说明需要等待什么条件"""


def _validate_result(result: Dict) -> None:
    """Ensure required fields exist with correct types; fill defaults."""
    defaults = {
        "sentiment_score": 0.0,
        "sentiment_label": "neutral",
        "news_summary": "",
        "news_sentiments": [],
        "technical_analysis": "",
        "investment_advice": [{"action": "HOLD", "rule": "AI分析", "detail": "暂无明确信号"}],
        "composite_score": 0.0,
        "signal": "HOLD",
        "signal_cn": "持有",
    }
    for k, v in defaults.items():
        if k not in result:
            result[k] = v

    score = result.get("sentiment_score", 0)
    if isinstance(score, (int, float)):
        result["sentiment_score"] = max(-1.0, min(1.0, float(score)))

    comp = result.get("composite_score", 0)
    if isinstance(comp, (int, float)):
        result["composite_score"] = max(-1.0, min(1.0, float(comp)))

    valid_signals = {"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"}
    if result.get("signal") not in valid_signals:
        result["signal"] = "HOLD"
        result["signal_cn"] = "持有"

    advice = result.get("investment_advice", [])
    if not isinstance(advice, list):
        result["investment_advice"] = [{"action": "HOLD", "rule": "AI分析", "detail": str(advice)}]
    for item in result["investment_advice"]:
        if not isinstance(item, dict):
            continue
        if item.get("action") not in ("BUY", "SELL", "HOLD"):
            item["action"] = "HOLD"

    # Validate news_sentiments
    ns = result.get("news_sentiments", [])
    if not isinstance(ns, list):
        result["news_sentiments"] = []
    else:
        valid_labels = {"positive", "negative", "neutral"}
        for item in ns:
            if not isinstance(item, dict):
                continue
            s = item.get("score", 0)
            if isinstance(s, (int, float)):
                item["score"] = max(-1.0, min(1.0, float(s)))
            else:
                item["score"] = 0.0
            if item.get("label") not in valid_labels:
                item["label"] = "neutral"
            if "summary" not in item:
                item["summary"] = ""
