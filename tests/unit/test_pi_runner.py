from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from code_diver.config.app_config import AppConfig
from code_diver.config.pi_config import PiConfig
from code_diver.pi import PiRunner

pytestmark = pytest.mark.unit


def test_pi_runner_tries_fallback_models(monkeypatch) -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            binary="pi",
            model="google/gemini-3.5-flash",
            fallback_models=["google/gemini-2.5-flash"],
        ),
    )
    commands: list[list[str]] = []

    def fake_call(command: list[str], env: dict[str, str], cwd: str) -> int:
        commands.append(command)
        assert cwd == str(config.root.resolve())
        return 1 if len(commands) == 1 else 0

    monkeypatch.setattr("subprocess.call", fake_call)

    assert PiRunner().run_print(config, Path("code-diver.yml"), "hello") == 0
    assert commands[0][commands[0].index("--model") + 1] == "google/gemini-3.5-flash"
    assert commands[1][commands[1].index("--model") + 1] == "google/gemini-2.5-flash"


def test_pi_runner_writes_json_mode_log(monkeypatch, tmp_path: Path) -> None:
    config = AppConfig(root=Path("/repo"), pi=PiConfig(binary="pi", provider="google", model="google/gemini-3.5-flash"))
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        timeout: int,
        cwd: str,
        check: bool,
    ):
        commands.append(command)
        assert cwd == str(config.root.resolve())
        assert check is False
        return SimpleNamespace(returncode=0, stdout='{"type":"agent_end"}\n', stderr="warn\n")

    monkeypatch.setattr("subprocess.run", fake_run)
    log_path = tmp_path / "pi.jsonl"

    assert PiRunner().run_print_logged(config, Path("code-diver.yml"), "hello", log_path) == 0

    assert "--mode" in commands[0]
    assert commands[0][commands[0].index("--mode") + 1] == "json"
    assert commands[0][-1] == "hello"
    text = log_path.read_text(encoding="utf-8")
    assert '{"type":"agent_end"}' in text
    assert '"type": "runner_stderr"' in text


def test_pi_runner_launch_status_hides_raw_command_and_empty_hypothesis(capsys) -> None:
    PiRunner()._print_launch_status(
        AppConfig(root=Path("/repo")),
        [
            "npx",
            "-y",
            "@earendil-works/pi-coding-agent",
            "--session-dir",
            "/repo/.code-diver/pi-sessions",
            "long prompt",
        ],
        model="google/gemini-3.1-flash-lite",
        toolset=None,
        hypothesis=None,
    )

    captured = capsys.readouterr()
    assert "google/gemini-3.1-flash-lite" in captured.err
    assert "/repo/.code-diver/pi-sessions" in captured.err
    assert "command" not in captured.err
    assert "hypothesis" not in captured.err
    assert "@earendil-works/pi-coding-agent" not in captured.err


def test_pi_runner_uses_project_cwd_for_local_npm_runtime(monkeypatch, tmp_path: Path) -> None:
    config = AppConfig(
        root=tmp_path / "repo",
        pi=PiConfig(
            binary="npm",
            launcher_args=["exec", "--", "pi"],
            model="google/gemini-3.1-flash-lite",
        ),
    )
    captured: dict[str, object] = {}

    class FakeRuntimeManager:
        package_root = tmp_path

        def cwd_for_command(self, command: list[str]) -> Path | None:
            return tmp_path if command[:4] == ["npm", "exec", "--", "pi"] else None

        def ensure_available(self) -> None:
            captured["ensured"] = True

        def command_for_execution(self, command: list[str]) -> list[str]:
            return [str(tmp_path / "node_modules" / ".bin" / "pi"), *command[4:]]

    def fake_call(command: list[str], **kwargs) -> int:
        captured["command"] = command
        captured["env"] = kwargs.get("env")
        captured["cwd"] = kwargs.get("cwd")
        return 0

    runner = PiRunner()
    runner.runtime_manager = FakeRuntimeManager()  # type: ignore[assignment]
    monkeypatch.setattr("subprocess.call", fake_call)

    assert runner.run_print(config, Path("code-diver.yml"), "hello") == 0
    assert captured["ensured"] is True
    assert captured["cwd"] == str((tmp_path / "repo").resolve())
    assert captured["command"][0] == str(tmp_path / "node_modules" / ".bin" / "pi")
    assert captured["env"]["CODE_DIVER_PACKAGE_ROOT"] == str(tmp_path.resolve())


def test_pi_runner_with_provider_and_model_override(monkeypatch) -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            binary="pi",
            provider="code-diver-local",
            model="default-model",
            fallback_models=["fallback-1", "fallback-2"],
        ),
    )
    captured: dict[str, object] = {}

    def fake_call(command: list[str], env: dict[str, str], cwd: str) -> int:
        captured["command"] = command
        captured["env"] = env
        return 0

    monkeypatch.setattr("subprocess.call", fake_call)
    runner = PiRunner()
    ret = runner.run_interactive(
        config,
        None,
        prompt="hello litellm",
        provider="litellm",
        model="vertex_ai/gemini-2.5-flash",
    )
    assert ret == 0
    cmd = captured["command"]
    assert "--provider" in cmd
    assert cmd[cmd.index("--provider") + 1] == "litellm"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "vertex_ai/gemini-2.5-flash"


def test_pi_runtime_manager_command_resolution(monkeypatch, tmp_path: Path) -> None:
    from code_diver.pi.pi_runtime_manager import PiRuntimeManager

    # Case 1: local binary in node_modules/.bin/pi exists
    pkg_root = tmp_path / "pkg"
    bin_dir = pkg_root / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    pi_bin = bin_dir / "pi"
    pi_bin.touch(mode=0o755)

    mgr = PiRuntimeManager(package_root=pkg_root)
    res = mgr.command_for_execution(["npm", "exec", "--", "pi", "-p", "hi"])
    assert res == [str(pi_bin), "-p", "hi"]

    # Case 2: local binary missing, but 'pi' on PATH
    pi_bin.unlink()
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/pi" if cmd == "pi" else None)
    res2 = mgr.command_for_execution(["npm", "exec", "--", "pi", "-p", "hi"])
    assert res2 == ["/usr/local/bin/pi", "-p", "hi"]

    # Case 3: neither exists, fallback to npm with --prefix
    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    res3 = mgr.command_for_execution(["npm", "exec", "--", "pi", "-p", "hi"])
    assert res3 == ["npm", "--prefix", str(pkg_root.resolve()), "exec", "--", "pi", "-p", "hi"]


def test_pi_command_builder_litellm_env(monkeypatch, tmp_path: Path) -> None:
    from code_diver.pi.pi_command_builder import PiCommandBuilder

    monkeypatch.delenv("LITE_LLM_KEY", raising=False)
    monkeypatch.setenv("LITELLM_API_KEY", "test-litellm-key-123")
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.custom.corp/v1")

    config = AppConfig(root=tmp_path / "repo")
    builder = PiCommandBuilder()
    env = builder.env(config, None, provider="litellm", model="vertex_ai/gemini-2.5-flash")

    assert env.get("LITELLM_API_KEY") == "test-litellm-key-123"
    assert env.get("LITE_LLM_KEY") == "test-litellm-key-123"
    assert env.get("LITELLM_BASE_URL") == "https://litellm.custom.corp/v1"
    assert env.get("OPENAI_API_KEY") == "test-litellm-key-123"
    assert env.get("CODE_DIVER_PROVIDER") == "litellm"
    assert env.get("CODE_DIVER_MODEL") == "vertex_ai/gemini-2.5-flash"

