# Stock News Sentiment Trading Strategy System

基于新闻情感分析的 A股 + 美股交易策略系统。从多个金融网站采集新闻，通过 FinBERT 模型进行情感分析，结合技术指标生成交易信号。

## Features

- **Multi-market**: Supports both US stocks and China A-shares
- **NLP Sentiment**: FinBERT for English, Chinese NLP model for A-share news
- **Technical Analysis**: RSI, MACD, MA, Bollinger Bands
- **Composite Signals**: Weighted scoring combining sentiment + technicals + news volume anomaly
- **Dual Output**: CLI reports (Rich tables) and Streamlit web dashboard

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
#    Edit config.yaml and set your finnhub_api_key

# 3. Run CLI report
python main.py

# 4. Run web dashboard
streamlit run app.py
```

## CLI Usage

```bash
# Analyze default watchlist
python main.py

# Analyze specific US stocks
python main.py --us AAPL TSLA NVDA

# Analyze specific A-shares
python main.py --cn 600519 000858

# Analyze both markets with custom lookback
python main.py --us AAPL --cn 600519 --days 5
```

## Architecture

```
Data Collection  -->  Sentiment Analysis  -->  Signal Generation  -->  Output
(Finnhub/Yahoo)      (FinBERT EN/CN)          (Composite Score)      (CLI/Web)
(akshare)            + Technical Analysis
                     (RSI/MACD/MA/BOLL)
```

## Signal Interpretation

| Score Range | Signal | Action |
|-------------|--------|--------|
| > 0.6 | STRONG BUY | 强买入 |
| 0.3 ~ 0.6 | BUY | 买入 |
| -0.3 ~ 0.3 | HOLD | 持有 |
| -0.6 ~ -0.3 | SELL | 卖出 |
| < -0.6 | STRONG SELL | 强卖出 |

## Disclaimer

This tool is for educational and research purposes only. It does not constitute financial advice. Always do your own research before making investment decisions.
