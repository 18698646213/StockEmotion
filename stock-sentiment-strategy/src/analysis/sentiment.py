"""Sentiment analysis engine using FinBERT for financial text.

Supports both English (US stock news) and Chinese (A-share news) sentiment analysis.
Each news item is scored on a scale of [-1, 1]:
  - [-1, -0.3]: Negative (bearish)
  - [-0.3, 0.3]: Neutral
  - [0.3, 1]:  Positive (bullish)
"""

import logging
from typing import List, Dict, Optional, Tuple

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

from src.data.news_us import NewsItem

logger = logging.getLogger(__name__)

# Singleton model cache
_models: Dict[str, Tuple] = {}


def _get_model(model_name: str):
    """Load and cache a HuggingFace model + tokenizer."""
    if model_name not in _models:
        logger.info("Loading model: %s (first time, may take a moment)...", model_name)
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        model.eval()
        _models[model_name] = (tokenizer, model)
    return _models[model_name]


def _is_chinese(text: str) -> bool:
    """Heuristic check: if >30% of chars are CJK, treat as Chinese."""
    if not text:
        return False
    cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk_count / max(len(text), 1) > 0.3


def analyze_sentiment_en(text: str) -> float:
    """Analyze English financial text sentiment using ProsusAI/finbert.

    Args:
        text: English text to analyze.

    Returns:
        Sentiment score in [-1, 1].
    """
    if not text or not text.strip():
        return 0.0

    model_name = "ProsusAI/finbert"
    try:
        tokenizer, model = _get_model(model_name)

        inputs = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True,
        )

        with torch.no_grad():
            outputs = model(**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1)

        # FinBERT labels: positive, negative, neutral
        probs = probs[0].tolist()
        # Map to [-1, 1]: positive * 1 + negative * (-1) + neutral * 0
        score = probs[0] * 1.0 + probs[1] * (-1.0) + probs[2] * 0.0
        return round(score, 4)

    except Exception as e:
        logger.error("EN sentiment analysis failed: %s", e)
        return 0.0


def analyze_sentiment_cn(text: str) -> float:
    """Analyze Chinese financial text sentiment.

    Uses a Chinese sentiment model from HuggingFace.

    Args:
        text: Chinese text to analyze.

    Returns:
        Sentiment score in [-1, 1].
    """
    if not text or not text.strip():
        return 0.0

    model_name = "uer/roberta-base-finetuned-chinanews-chinese"
    try:
        tokenizer, model = _get_model(model_name)

        inputs = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True,
        )

        with torch.no_grad():
            outputs = model(**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1)

        probs = probs[0].tolist()
        num_labels = len(probs)

        if num_labels == 2:
            # Binary: [negative, positive]
            score = probs[1] - probs[0]
        elif num_labels == 3:
            # [negative, neutral, positive]
            score = probs[2] * 1.0 + probs[0] * (-1.0)
        else:
            # Multi-class: map linearly from [0, num_labels-1] to [-1, 1]
            weighted = sum(i * p for i, p in enumerate(probs))
            score = (weighted / max(num_labels - 1, 1)) * 2 - 1

        return round(max(-1.0, min(1.0, score)), 4)

    except Exception as e:
        logger.error("CN sentiment analysis failed: %s", e)
        return 0.0


def analyze_news_sentiment(news_items: List[NewsItem]) -> List[Dict]:
    """Analyze sentiment for a list of news items.

    Automatically detects language and routes to the appropriate model.

    Args:
        news_items: List of NewsItem objects.

    Returns:
        List of dicts: {news_item, score, label}
        where label is one of 'positive', 'negative', 'neutral'.
    """
    results = []
    for item in news_items:
        # Use title + summary for analysis
        text = f"{item.title}. {item.summary}" if item.summary else item.title

        if _is_chinese(text):
            score = analyze_sentiment_cn(text)
        else:
            score = analyze_sentiment_en(text)

        if score > 0.3:
            label = "positive"
        elif score < -0.3:
            label = "negative"
        else:
            label = "neutral"

        results.append({
            "news_item": item,
            "score": score,
            "label": label,
        })

    return results


def compute_aggregate_sentiment(sentiment_results: List[Dict]) -> float:
    """Compute the aggregate sentiment score from analysis results.

    Args:
        sentiment_results: Output of analyze_news_sentiment.

    Returns:
        Average sentiment score in [-1, 1], or 0.0 if no results.
    """
    if not sentiment_results:
        return 0.0

    scores = [r["score"] for r in sentiment_results]
    return round(sum(scores) / len(scores), 4)
