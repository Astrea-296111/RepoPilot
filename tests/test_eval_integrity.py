"""Guard the attribution and denominators of benchmark comparisons."""
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_full_context_exposes_exact_helper_source(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "eval"))
    one = importlib.import_module("run_one_shot")
    tasks = json.loads((ROOT / "eval" / "benchmark_tasks.json").read_text(encoding="utf-8"))
    task = next(item for item in tasks if item["id"] == "shared_rounding_policy")
    repo = ROOT / task["repo"]
    baseline = {"stdout": "failing assertion", "stderr": ""}
    full, files = one.build_context(repo, task, baseline, mode="full")
    retrieved, selected = one.build_context(repo, task, baseline, mode="retrieved")
    helper = "app/internal/number_ops.py"
    source = (repo / helper).read_text(encoding="utf-8")
    assert helper in files and source in full
    assert helper not in selected and source not in retrieved
    assert "test_hidden_eval.py" not in files


def test_merge_rejects_duplicate_and_missing_repeats(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "eval"))
    merge = importlib.import_module("merge_shards").merge
    config = {"model": "scripted FakeLLM", "runs_per_task": 2, "context_mode": "full"}

    def shard(name, task_id, run):
        path = tmp_path / name
        data = {"summary": {"runner": "one-shot", "model": "scripted FakeLLM"},
                "config": config,
                "records": [{"task_id": task_id, "run": run, "category": "test", "difficulty": "hard",
                             "resolved": True, "failure_category": None,
                             "model_call": {"total_tokens": 10, "duration_seconds": 1}, "patch_count": 1}]}
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    first = shard("a.json", "task_a", 1)
    second = shard("b.json", "task_a", 2)
    merged = merge([first, second], expected_task_count=1)
    assert merged["summary"]["runs"] == 2
    with pytest.raises(ValueError, match="duplicate task/run"):
        merge([first, first])
    with pytest.raises(ValueError, match="incomplete repeats"):
        merge([first])


def test_compare_refuses_silent_unpaired_denominators(tmp_path):
    summary = {"runner": "agent", "model": "test", "suite": "test", "resolved_runs": 1,
               "runs": 1, "run_resolved_rate": 1.0, "median_total_tokens": 10,
               "median_duration_seconds": 1}
    agent = {"summary": summary, "records": [{"task_id": "a", "run": 1, "resolved": True}]}
    one = {"summary": {**summary, "runner": "one-shot"},
           "records": [{"task_id": "b", "run": 1, "resolved": True}]}
    a_path, o_path = tmp_path / "agent.json", tmp_path / "one.json"
    a_path.write_text(json.dumps(agent), encoding="utf-8")
    o_path.write_text(json.dumps(one), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "eval" / "compare_results.py"), str(a_path), str(o_path),
                             "--json-out", str(tmp_path / "comparison.json"),
                             "--md-out", str(tmp_path / "comparison.md")], capture_output=True, text=True)
    assert result.returncode != 0
    assert "unpaired records" in result.stderr
