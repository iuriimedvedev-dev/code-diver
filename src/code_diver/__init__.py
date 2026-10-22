"""Code Diver CLI package."""

from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = ["__version__", "build_version"]

# The released version of this package. Keep in sync with the git tag that
# shipped it; `git describe` is the source of truth for a checkout (see
# build_version), which also reports whether the tree had uncommitted changes
# when a run was made - a version string that cannot say "dirty" makes a
# benchmark result impossible to reproduce.
__version__ = "0.6.5"


def _git_describe(repo: Path) -> str | None:
    """`git describe --tags --always --dirty` for the checkout, or None.

    Returns None whenever git is unavailable, the directory is not a checkout,
    or the command fails - callers fall back to ``__version__``.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    described = result.stdout.strip()
    return described or None


def build_version(repo: Path | None = None) -> str:
    """Version string for this installation, including the checkout state.

    Prefers the git description of the source checkout, because a value copied
    into a package constant cannot tell a benchmark consumer that the tree was
    modified. Falls back to ``__version__`` when git cannot answer.
    """
    root = repo or Path(__file__).resolve().parent.parent
    return _git_describe(root) or __version__
