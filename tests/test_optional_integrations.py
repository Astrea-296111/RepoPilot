"""Base installation remains usable without optional SDKs or external services."""
import builtins
import subprocess
import sys

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM


def test_base_cli_custom_runtime_smoke(runtime_repo):
    result = subprocess.run([sys.executable, "-m", "repopilot.cli", "run", str(runtime_repo),
                             "fix duplicate email", "--fake-demo", "--executor", "local", "--approval", "auto"],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Status: completed" in result.stdout


def test_tracing_disabled_does_not_import_sdk_or_contact_exporter(runtime_repo, monkeypatch):
    original = builtins.__import__

    def block(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise AssertionError("disabled tracing must not import OpenTelemetry")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block)
    pilot = RepoPilot(runtime_repo, FakeLLM(demo_responses()),
                      Settings(otel_enabled=False, otel_endpoint="not a valid endpoint"),
                      executor="local", approval="auto")
    assert pilot.tracing.provider is None and pilot.run("fix").status == "completed"


def test_missing_optional_dependencies_give_installation_errors(runtime_repo):
    script = '''
import builtins
from pathlib import Path
import sys
from repopilot.agent.agent import RepoPilot
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.mcp_server import create_server
original = builtins.__import__
def block(name, *args, **kwargs):
    if name.startswith(("langgraph", "mcp", "opentelemetry.sdk")):
        raise ModuleNotFoundError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = block
for extra, operation in [
    ("langgraph", lambda: RepoPilot(Path(sys.argv[1]), FakeLLM([]), Settings(), runtime="langgraph")),
    ("mcp", lambda: create_server(Path(sys.argv[1]))),
    ("observability", lambda: RepoPilot(Path(sys.argv[1]), FakeLLM([]), Settings(otel_enabled=True)))]:
    try:
        operation()
    except ValueError as exc:
        assert "pip install" in str(exc) and extra in str(exc), str(exc)
    else:
        raise AssertionError("missing extra was accepted: " + extra)
print("All optional integrations report actionable installation errors")
'''
    result = subprocess.run([sys.executable, "-c", script, str(runtime_repo)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
