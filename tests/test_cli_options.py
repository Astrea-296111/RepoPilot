"""Explicit CLI booleans override environment; omission inherits it."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import repopilot.cli as cli
from repopilot.config import Settings


@pytest.mark.parametrize("environment,flags,expected", [
    ("1", [], True), ("0", [], False),
    ("1", ["--no-reflection", "--no-memory"], False),
    ("0", ["--reflection", "--memory"], True),
])
def test_explicit_feature_flags_override_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    environment: str, flags: list[str], expected: bool,
) -> None:
    monkeypatch.setenv("REPOPILOT_REFLECTION", environment)
    monkeypatch.setenv("REPOPILOT_MEMORY", environment)
    captured = []

    class CaptureAgent:
        def __init__(self, repo: Path, llm: object, settings: Settings, **kwargs: object) -> None:
            captured.append((settings.reflection_enabled, settings.memory_enabled))

        def run(self, task: str) -> SimpleNamespace:
            return SimpleNamespace(id="capture", status="completed", test_status="passed",
                current_step=0, summary="capture only", error="", final_diff="")

    monkeypatch.setattr(cli, "RepoPilot", CaptureAgent)
    monkeypatch.setattr(cli, "_llm", lambda *args: None)
    result = CliRunner().invoke(cli.app, ["run", str(tmp_path), "check flags", *flags])
    assert result.exit_code == 0, result.output
    assert captured == [(expected, expected)]
