"""Regression tests for `scripts/clobber_guard.py`.

`RefuseToClobberError`, `allow_overwrite_from_env()`, and `guard_against_clobber()` used
to be duplicated verbatim across `scripts/rejudge_answer_report.py`,
`scripts/run_postrank_h2_benchmark.py`, and `scripts/run_postrank_h2_deterministic.py`
because two separate fix rounds landed the guard in each script without a shared home.
These tests pin the shared module's own behaviour, and that each of the three call sites
now resolves the same class/functions from it (rather than a private, drifted copy).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered in sys.modules BEFORE exec_module: `run_postrank_h2_deterministic.py` defines
    # a `slots=True` dataclass, and dataclasses on 3.12+ resolve `cls.__module__` via
    # `sys.modules` while processing annotations -- without this, exec_module() raises
    # `AttributeError` because the module isn't registered yet. Mirrors the same fix in
    # tests/unit/test_run_postrank_h2_deterministic_naming.py and
    # tests/unit/test_postrank_h2_runner.py.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = load_script("clobber_guard")


def test_allow_overwrite_from_env_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    assert GUARD.allow_overwrite_from_env() is False


@pytest.mark.parametrize("falsy_value", ["", "0", "false", "False"])
def test_allow_overwrite_from_env_falsy_values(monkeypatch: pytest.MonkeyPatch, falsy_value: str) -> None:
    monkeypatch.setenv("ALLOW_OVERWRITE", falsy_value)
    assert GUARD.allow_overwrite_from_env() is False


def test_allow_overwrite_from_env_truthy_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_OVERWRITE", "1")
    assert GUARD.allow_overwrite_from_env() is True


def test_guard_raises_when_any_path_exists(tmp_path: Path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text("{}", encoding="utf-8")
    missing = tmp_path / "missing.json"

    with pytest.raises(GUARD.RefuseToClobberError, match=str(existing)):
        GUARD.guard_against_clobber(missing, existing, allow_overwrite=False)


def test_guard_ignores_none_paths(tmp_path: Path) -> None:
    GUARD.guard_against_clobber(None, tmp_path / "missing.json", allow_overwrite=False)


def test_guard_permits_overwrite_when_allowed(tmp_path: Path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text("{}", encoding="utf-8")

    GUARD.guard_against_clobber(existing, allow_overwrite=True)


def test_guard_passes_when_nothing_exists(tmp_path: Path) -> None:
    GUARD.guard_against_clobber(tmp_path / "a.json", tmp_path / "b.json", allow_overwrite=False)


def test_module_is_importable_standalone_without_code_diver(tmp_path: Path) -> None:
    """The postrank scripts must not gain heavy `code_diver` imports through this module.

    Runs in a fresh subprocess interpreter (no repo-installed environment assumptions
    beyond stdlib) so a future edit that quietly adds a `code_diver` import here would
    fail this test even though it might still pass inside the project's own venv.
    """
    script = (
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('clobber_guard', "
        f"{str(REPO_ROOT / 'scripts' / 'clobber_guard.py')!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "import sys\n"
        "assert not any('code_diver' in name for name in sys.modules), sys.modules.keys()\n"
        "assert module.RefuseToClobberError is not None\n"
        "assert callable(module.allow_overwrite_from_env)\n"
        "assert callable(module.guard_against_clobber)\n"
        "print('ok')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-S", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


@pytest.mark.parametrize(
    "script_name",
    ["rejudge_answer_report", "run_postrank_h2_benchmark", "run_postrank_h2_deterministic"],
)
def test_call_site_resolves_guard_symbols_from_shared_module(script_name: str) -> None:
    """Each call site must load `scripts/clobber_guard.py` by path and re-export its
    symbols verbatim, not define its own (driftable) copy.

    Each `load_script()` call -- here and in the caller's own `importlib` loading of
    `clobber_guard.py` -- executes the target file fresh with no `sys.modules` caching
    (the same idiom `scripts/rerun_meta_judge_failed.py` uses for its sibling import), so
    two independently loaded copies of `clobber_guard.py` are two distinct module objects.
    Comparing class identity against a *third*, separately loaded `GUARD` copy would
    therefore fail even for a correct call site; instead this asserts that each call site
    resolves its `RefuseToClobberError`/etc. from *its own* loaded `clobber_guard` module,
    and that that module was loaded from the real shared file on disk.
    """
    caller = load_script(script_name)
    shared_module_path = (REPO_ROOT / "scripts" / "clobber_guard.py").resolve()

    assert Path(caller.clobber_guard.__file__).resolve() == shared_module_path
    assert caller.RefuseToClobberError is caller.clobber_guard.RefuseToClobberError
    assert caller.allow_overwrite_from_env is caller.clobber_guard.allow_overwrite_from_env
    assert caller.guard_against_clobber is caller.clobber_guard.guard_against_clobber
    assert caller.RefuseToClobberError.__module__ == "clobber_guard"
