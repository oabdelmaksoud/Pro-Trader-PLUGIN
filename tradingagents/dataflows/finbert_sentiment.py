"""
CooperCorp PRJ-002 — FinBERT NLP Sentiment Scoring
Uses ProsusAI/finbert to score financial headlines.
Gracefully degrades if transformers not installed.
"""
import time
from typing import Optional, List

_model = None
_model_loaded = False
_cache = {}  # text -> (score_dict, timestamp)
CACHE_TTL = 900  # 15 min


def _load_model():
    global _model, _model_loaded
    if _model_loaded:
        return _model
    try:
        from transformers import pipeline
        _model = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            return_all_scores=True,
            truncation=True,
            max_length=512
        )
        _model_loaded = True
        print("[finbert] Model loaded: ProsusAI/finbert")
    except ImportError:
        print("[finbert] transformers not installed — pip install transformers torch")
        _model_loaded = True  # Don't retry
        _model = None
    except Exception as e:
        print(f"[finbert] Load error: {e}")
        _model_loaded = True
        _model = None
    return _model


def score_headline(text: str) -> Optional[dict]:
    """Score a single headline. Returns {label, score, confidence} or None."""
    if not text or not text.strip():
        return None
    try:
        # Check cache
        cache_key = text[:200]
        if cache_key in _cache:
            result, ts = _cache[cache_key]
            if time.time() - ts < CACHE_TTL:
                return result

        model = _load_model()
        if model is None:
            return None

        outputs = model(text[:512])[0]  # list of {label, score}
        label_map = {o["label"].lower(): o["score"] for o in outputs}

        pos = label_map.get("positive", 0)
        neg = label_map.get("negative", 0)
        neu = label_map.get("neutral", 0)

        best_label = max(label_map, key=label_map.get)
        best_score = label_map[best_label]

        result = {
            "label": best_label,
            "score": best_score,
            "confidence": best_score,
            "positive": pos,
            "negative": neg,
            "neutral": neu
        }
        _cache[cache_key] = (result, time.time())
        return result
    except Exception as e:
        print(f"[finbert] score_headline error: {e}")
        return None


def score_headlines(headlines: list) -> dict:
    """Batch score multiple headlines. Returns aggregate stats."""
    results = []
    for h in headlines[:20]:  # limit batch size
        try:
            text = h if isinstance(h, str) else h.get("title", h.get("headline", ""))
            if text:
                r = score_headline(text)
                if r:
                    results.append(r)
        except Exception:
            continue
    if not results:
        return {}
    pos = sum(r.get("positive", 0) for r in results) / len(results)
    neg = sum(r.get("negative", 0) for r in results) / len(results)
    neu = sum(r.get("neutral", 0) for r in results) / len(results)
    return {"positive": pos, "negative": neg, "neutral": neu, "count": len(results)}


def get_ticker_sentiment_score(headlines_list: list) -> dict:
    """
    Takes list of {title:...} dicts or strings.
    Returns {finbert_score: -1 to +1, positive_pct, negative_pct, neutral_pct, headline_count, available}
    """
    if not headlines_list:
        return {"finbert_score": 0.0, "positive_pct": 0, "negative_pct": 0,
                "neutral_pct": 0, "headline_count": 0, "available": False}

    model = _load_model()
    if model is None:
        return {"finbert_score": 0.0, "positive_pct": 0, "negative_pct": 0,
                "neutral_pct": 0, "headline_count": 0, "available": False}

    results = []
    for item in headlines_list[:25]:
        try:
            text = item if isinstance(item, str) else item.get("title", item.get("headline", ""))
            if text:
                r = score_headline(str(text))
                if r:
                    results.append(r)
        except Exception:
            continue

    if not results:
        return {"finbert_score": 0.0, "positive_pct": 0, "negative_pct": 0,
                "neutral_pct": 0, "headline_count": 0, "available": True}

    pos_pct = sum(1 for r in results if r["label"] == "positive") / len(results)
    neg_pct = sum(1 for r in results if r["label"] == "negative") / len(results)
    neu_pct = sum(1 for r in results if r["label"] == "neutral") / len(results)

    # Score: +1 for all positive, -1 for all negative
    finbert_score = pos_pct - neg_pct

    return {
        "finbert_score": round(finbert_score, 3),
        "positive_pct": round(pos_pct * 100, 1),
        "negative_pct": round(neg_pct * 100, 1),
        "neutral_pct": round(neu_pct * 100, 1),
        "headline_count": len(results),
        "available": True
    }
