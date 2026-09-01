from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .ltr_feature_row import LTR_FEATURE_NAMES, LtrFeatureRow

logger = logging.getLogger(__name__)

LTR_MANIFEST_VERSION = 1

FORMAT_LINEAR = "linear"
FORMAT_SKLEARN_JOBLIB = "sklearn_joblib"
FORMAT_LIGHTGBM_TXT = "lightgbm_txt"


@dataclass(slots=True)
class LtrRankerModel:
    """A trained ranker loaded from disk.

    Every failure mode -- no artifact, unreadable manifest, feature list drift, a backend
    library that is not installed here -- resolves to `load` returning None, so the caller
    keeps the hand-tuned fused ordering. A learned ranker that cannot load must never be
    the difference between a working and a broken search.
    """

    feature_names: tuple[str, ...]
    predict: Callable[[Sequence[Sequence[float]]], list[float]]

    @classmethod
    def load(cls, path: Path | str | None) -> LtrRankerModel | None:
        if not path:
            return None
        manifest_path = Path(path)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.debug("no LTR model artifact at %s, keeping hand-tuned ranking", manifest_path)
            return None
        except Exception:
            logger.warning("unreadable LTR model artifact at %s, keeping hand-tuned ranking", manifest_path)
            return None
        return cls._from_manifest(manifest, manifest_path)

    @classmethod
    def _from_manifest(cls, manifest: object, manifest_path: Path) -> LtrRankerModel | None:
        if not isinstance(manifest, dict):
            logger.warning("LTR model manifest %s is not a mapping, keeping hand-tuned ranking", manifest_path)
            return None
        feature_names = tuple(str(name) for name in manifest.get("feature_names") or ())
        if feature_names != LTR_FEATURE_NAMES:
            logger.warning(
                "LTR model artifact %s was trained on a different feature list, keeping hand-tuned ranking",
                manifest_path,
            )
            return None
        model_format = str(manifest.get("format") or "")
        try:
            predict = cls._predictor(model_format, manifest, manifest_path)
        except Exception:
            logger.warning("failed to load LTR model %s, keeping hand-tuned ranking", manifest_path, exc_info=True)
            return None
        if predict is None:
            return None
        return cls(feature_names=feature_names, predict=predict)

    @classmethod
    def _predictor(
        cls,
        model_format: str,
        manifest: dict[str, object],
        manifest_path: Path,
    ) -> Callable[[Sequence[Sequence[float]]], list[float]] | None:
        if model_format == FORMAT_LINEAR:
            weights = [float(value) for value in manifest.get("weights") or ()]
            bias = float(manifest.get("bias") or 0.0)
            if len(weights) != len(LTR_FEATURE_NAMES):
                logger.warning("LTR linear artifact %s has a mismatched weight count", manifest_path)
                return None

            def predict_linear(rows: Sequence[Sequence[float]]) -> list[float]:
                return [bias + sum(w * f for w, f in zip(weights, row, strict=True)) for row in rows]

            return predict_linear

        model_file = manifest.get("model_file")
        if not model_file:
            logger.warning("LTR artifact %s declares format %r but no model_file", manifest_path, model_format)
            return None
        model_path = manifest_path.parent / str(model_file)

        if model_format == FORMAT_SKLEARN_JOBLIB:
            import joblib

            estimator = joblib.load(model_path)

            def predict_sklearn(rows: Sequence[Sequence[float]]) -> list[float]:
                return [float(value) for value in estimator.predict([list(row) for row in rows])]

            return predict_sklearn

        if model_format == FORMAT_LIGHTGBM_TXT:
            import lightgbm

            booster = lightgbm.Booster(model_file=str(model_path))

            def predict_lightgbm(rows: Sequence[Sequence[float]]) -> list[float]:
                return [float(value) for value in booster.predict([list(row) for row in rows])]

            return predict_lightgbm

        logger.warning("unknown LTR model format %r in %s", model_format, manifest_path)
        return None

    def score(self, rows: Sequence[LtrFeatureRow]) -> list[float] | None:
        """Model score per row, or None when scoring fails (caller keeps its own order)."""
        if not rows:
            return []
        try:
            scores = self.predict([row.features for row in rows])
        except Exception:
            logger.warning("LTR model scoring failed, keeping hand-tuned ranking", exc_info=True)
            return None
        if len(scores) != len(rows):
            logger.warning("LTR model returned %d scores for %d rows", len(scores), len(rows))
            return None
        return [float(score) for score in scores]
