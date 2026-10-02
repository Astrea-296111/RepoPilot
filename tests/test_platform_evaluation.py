"""One combined CLI path and report semantics, without external model calls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("runtime", ["custom", "langgraph"])
def test_full_feature_cli_demo(runtime_repo, runtime):
    pytest.importorskip("mcp")
    pytest.importorskip("rank_bm25")
    pytest.importorskip("faiss")
    if runtime == "langgraph":
        pytest.importorskip("langgraph")
    result = subprocess.run([sys.executable, "-m", "repopilot.cli", "run", str(runtime_repo),
        "fix duplicate email", "--runtime", runtime, "--tool-backend", "mcp", "--retrieval", "hybrid",
        "--reflection", "--memory", "--fake-demo", "--executor", "local", "--approval", "auto"],
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    from repopilot.session.store import SessionStore
    state = SessionStore(runtime_repo).list()[0]
    assert state.status == "completed" and len(state.reflections) == 5
    assert state.retrieval_results and state.memory_enabled


def test_report_does_not_invent_monetary_cost(tmp_path):
    spec = importlib.util.spec_from_file_location("evaluation_report", ROOT / "eval/report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = {"config": {"evidence_type": "scripted"},
        "summary": {"model": "FakeLLM", "task_count": 1, "runs": 1, "resolved_runs": 0,
                    "run_resolved_rate": 0, "failure_categories": {"environment_failure": 1}},
        "records": [{"task_id": "broken", "run": 1, "resolved": False, "failure_category": "environment_failure"}]}
    output = tmp_path / "report.md"
    module.write_report(report, output)
    content = output.read_text()
    assert "脚本化工程验证" in content and "未测 / 不适用" in content
    assert "environment_failure" in content and "缺失" in content
    report["config"] = {"evidence_type": "real_model", "input_price_per_million": 2.0, "output_price_per_million": 4.0}
    report["summary"]["model"] = "test-model"
    report["records"][0]["agent"] = {"token_usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}}
    module.write_report(report, output)
    assert "0.004000" in output.read_text()
