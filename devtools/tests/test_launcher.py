"""Launch/reopen/cleanup without opening real browser windows or credentials."""

from types import SimpleNamespace

import pytest

import start_agent_lab as launcher
from devtools.agent_lab.config import TOKEN_ENV
from devtools.agent_lab.credentials import Vault


class MemoryVault:
    def __init__(self, values=None):
        self.values = values or {}

    def read(self, provider):
        return self.values.get(provider)

    def write(self, provider, value):
        self.values[provider] = value

    def delete(self, provider):
        self.values.pop(provider, None)


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "RUNTIME", tmp_path / ".lab")
    return tmp_path


def test_reopen_existing_lab_without_installing_or_starting(monkeypatch, local, capsys):
    token = "private-launch-token"
    monkeypatch.setattr(launcher, "Vault", lambda: MemoryVault({"launcher": token}))
    monkeypatch.setattr(launcher, "status", lambda value: value == token)
    monkeypatch.setattr(launcher, "prepare_environment", lambda: pytest.fail("Unexpected installation"))
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    launcher.main()
    assert opened == [launcher.URL + "/#" + token]
    assert token not in capsys.readouterr().out


def test_occupied_port_never_starts_or_stops_another_process(monkeypatch, local):
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def connect_ex(self, address): return 0

    monkeypatch.setattr(launcher, "Vault", MemoryVault)
    monkeypatch.setattr(launcher.socket, "socket", Probe)
    monkeypatch.setattr(launcher, "prepare_environment", lambda: pytest.fail("Unexpected installation"))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: pytest.fail("Unexpected process"))
    with pytest.raises(RuntimeError, match="occupied"):
        launcher.main()


def test_failed_start_cleans_only_its_credential(monkeypatch, local):
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def connect_ex(self, address): return 1

    vault = MemoryVault({"groq": "keep-personal-key"})
    monkeypatch.setattr(launcher, "Vault", lambda: vault)
    monkeypatch.setattr(launcher.socket, "socket", Probe)
    monkeypatch.setattr(launcher, "prepare_environment", lambda: None)
    monkeypatch.setattr(launcher, "status", lambda token: False)
    def start(args, **kwargs):
        assert TOKEN_ENV in kwargs["env"]
        return SimpleNamespace(poll=lambda: 1)
    monkeypatch.setattr(launcher.subprocess, "Popen", start)
    with pytest.raises(RuntimeError, match="did not start"):
        launcher.main()
    assert vault.values == {"groq": "keep-personal-key"}


def test_environment_targets_only_this_worktree(monkeypatch, local):
    (local / "agent").mkdir()
    (local / "agent/uv.lock").write_text("lock")
    (local / "agent/pyproject.toml").write_text("project")
    launcher.RUNTIME.mkdir()
    monkeypatch.setattr(launcher, "PYTHON", local / "agent/.venv/Scripts/python.exe")
    monkeypatch.setattr(launcher.shutil, "which", lambda value: "uv")
    monkeypatch.setenv("VIRTUAL_ENV", "another-worktree")
    def sync(args, *, check, env):
        assert check and "--frozen" in args
        assert args[args.index("--project") + 1] == str(local / "agent")
        assert env["UV_PROJECT_ENVIRONMENT"] == str(local / "agent/.venv")
        assert "VIRTUAL_ENV" not in env
    monkeypatch.setattr(launcher.subprocess, "run", sync)
    launcher.prepare_environment()
    assert (launcher.RUNTIME / "dependencies.sha256").exists()


def test_credential_namespace_is_separate_from_old_lab():
    assert Vault.target("groq") == "trego.agent-v2-lab/groq"
