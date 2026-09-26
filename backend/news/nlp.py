"""NLP models behind small interfaces so they can be replaced or faked.

Fail-closed: if a model cannot be loaded (package missing, download blocked),
callers get ModelUnavailableError. Sentiment is then recorded as UNKNOWN —
never guessed — and document search is disabled.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from app.core.config_file import get_config

log = logging.getLogger(__name__)


class ModelUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Sentiment:
    label: str  # positive | negative | neutral
    positive: float
    negative: float
    neutral: float

    @property
    def score(self) -> float:
        """Signed sentiment in [-1, 1]."""
        return self.positive - self.negative


class SentimentModel(Protocol):
    name: str

    def predict(self, texts: list[str]) -> list[Sentiment]: ...


class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: list[str]) -> npt.NDArray[np.float32]: ...


class FinBert:
    def __init__(self, model_name: str) -> None:
        self.name = model_name
        try:
            from transformers import pipeline
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ModelUnavailableError(
                "transformers is not installed (pip install .[ml])"
            ) from exc
        try:
            self._pipe: Any = pipeline("text-classification", model=model_name, top_k=None)
        except Exception as exc:
            raise ModelUnavailableError(
                f"cannot load {model_name}: {exc.__class__.__name__}"
            ) from exc

    def predict(self, texts: list[str]) -> list[Sentiment]:
        out: list[Sentiment] = []
        for scores in self._pipe(texts, truncation=True, batch_size=16):
            d = {s["label"].lower(): float(s["score"]) for s in scores}
            label = max(d, key=lambda k: d[k])
            out.append(
                Sentiment(
                    label, d.get("positive", 0.0), d.get("negative", 0.0), d.get("neutral", 0.0)
                )
            )
        return out


class MiniLM:
    def __init__(self, model_name: str, dim: int) -> None:
        self.name, self.dim = model_name, dim
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise ModelUnavailableError("sentence-transformers is not installed") from exc
        try:
            self._m: Any = SentenceTransformer(model_name)
        except Exception as exc:
            raise ModelUnavailableError(
                f"cannot load {model_name}: {exc.__class__.__name__}"
            ) from exc

    def encode(self, texts: list[str]) -> npt.NDArray[np.float32]:
        vecs = self._m.encode(texts, normalize_embeddings=True, batch_size=32)
        arr = np.asarray(vecs, dtype=np.float32)
        if arr.shape[1] != self.dim:
            raise ModelUnavailableError(f"embedding dim {arr.shape[1]} != configured {self.dim}")
        return arr


_lock = threading.Lock()
_sentiment: SentimentModel | None = None
_embedder: Embedder | None = None
_errors: dict[str, str] = {}


def get_sentiment_model() -> SentimentModel:
    global _sentiment
    with _lock:
        if _sentiment is None:
            if "sentiment" in _errors:
                raise ModelUnavailableError(_errors["sentiment"])
            try:
                _sentiment = FinBert(get_config().news.sentiment_model)
            except ModelUnavailableError as exc:
                _errors["sentiment"] = str(exc)
                log.warning("sentiment model unavailable: %s", exc)
                raise
        return _sentiment


def get_embedder() -> Embedder:
    global _embedder
    with _lock:
        if _embedder is None:
            if "embedder" in _errors:
                raise ModelUnavailableError(_errors["embedder"])
            cfg = get_config().news
            try:
                _embedder = MiniLM(cfg.embedding_model, cfg.embedding_dim)
            except ModelUnavailableError as exc:
                _errors["embedder"] = str(exc)
                log.warning("embedding model unavailable: %s", exc)
                raise
        return _embedder


def set_models(sentiment: SentimentModel | None, embedder: Embedder | None) -> None:
    """Install explicit model instances (tests, or a service warm-up)."""
    global _sentiment, _embedder
    with _lock:
        _sentiment, _embedder = sentiment, embedder
        _errors.clear()


def model_status() -> dict[str, str]:
    return {
        "sentiment": _sentiment.name if _sentiment else _errors.get("sentiment", "not loaded"),
        "embedder": _embedder.name if _embedder else _errors.get("embedder", "not loaded"),
    }


def mark_unavailable(reason: str) -> None:
    """Force both models into the unavailable state (tests / kill switch for NLP)."""
    global _sentiment, _embedder
    with _lock:
        _sentiment, _embedder = None, None
        _errors["sentiment"] = reason
        _errors["embedder"] = reason
