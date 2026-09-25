from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


def is_huggingface_repo_id(model_name: str) -> bool:
    """Return True if model_name looks like a Hugging Face repo (e.g. 'org/model-name')."""
    if not model_name or os.path.exists(model_name):
        return False
    parts = model_name.strip().split("/")
    if len(parts) == 2 and parts[0] and parts[1]:
        # Exclude typical URLs or Windows paths
        if not parts[0].startswith(("http:", "https:", ".", "/")):
            return True
    return False


def ensure_model_downloaded(
    repo_id: str,
    *,
    local_dir: Path | str | None = None,
    revision: str | None = None,
    token: str | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> Path | str:
    """Ensure a model from Hugging Face is downloaded locally.

    Returns the path to the downloaded snapshot or repo_id if already cached or download fails gracefully.
    """
    if not is_huggingface_repo_id(repo_id):
        return repo_id

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        logger.warning("huggingface_hub is not installed; skipping pre-download for %s", repo_id)
        return repo_id

    resolved_token = token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

    if progress_callback:
        progress_callback(f"Downloading model {repo_id} from Hugging Face...")

    try:
        downloaded_path = snapshot_download(
            repo_id=repo_id,
            revision=revision,
            token=resolved_token,
            local_dir=str(local_dir) if local_dir else None,
        )
        if progress_callback:
            progress_callback(f"Model {repo_id} ready at {downloaded_path}")
        return Path(downloaded_path)
    except Exception as exc:
        logger.warning("Auto-download for HF model %s failed: %s", repo_id, exc)
        if progress_callback:
            progress_callback(f"Note: Could not pre-download {repo_id} ({exc}). Runtime will attempt download on startup.")
        return repo_id
