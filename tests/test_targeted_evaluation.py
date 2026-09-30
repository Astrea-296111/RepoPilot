"""Denominator and opt-in safeguards; fixtures reuse historical data, never claim new trials."""
import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def targeted(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "eval"))
    report = importlib.import_module("summarize_targeted")
    old = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "eval/evidence/2026-09-30/shards").glob("external-*.json")]
    docs = [d for d in old if "records" in d]
    config = {f: docs[0][f] for f in report.FIELDS}
    config["shards"] = 4
    inputs = []
    for mode in ("agent", "oneshot"):
        for index, task in enumerate(report.TARGETED_TASK_IDS):
            records = [r for d in docs for r in d["records"] if r["mode"] == mode and r["task_id"] == task]
            doc = {**config, "mode": mode, "shard": index, "runtime": "custom" if mode == "agent" else "oneshot",
                   "task_ids": list(report.TARGETED_TASK_IDS), "records": records}
            path = tmp_path / f"external-{mode}-{index}.json"
            path.write_text(json.dumps(doc))
            inputs.append(path)
    return report, inputs


def test_targeted_reporting_preserves_known_historical_slice(targeted):
    module, inputs = targeted
    result = module.summarize(inputs)
    assert result["scope"]["trials"] == 24
    assert result["methods"]["agent"]["resolved"] == 7
    assert result["methods"]["agent"]["completed_and_resolved"] == 5
    assert result["methods"]["agent"]["loop_detection"] == 5
    assert result["methods"]["oneshot"]["resolved"] == 10


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "config", "runtime"])
def test_targeted_reporting_rejects_incomplete_or_mixed_data(targeted, corruption):
    module, inputs = targeted
    if corruption == "missing":
        inputs = inputs[:-1]
    elif corruption == "duplicate":
        inputs = [inputs[0], inputs[0], *inputs[2:]]
    else:
        data = json.loads(inputs[0].read_text(encoding="utf-8"))
        if corruption == "config":
            data["max_context_chars"] += 1
        else:
            data["runtime"] = "langgraph"
        inputs[0].write_text(json.dumps(data))
    with pytest.raises(ValueError):
        module.summarize(inputs)


@pytest.mark.parametrize("scope,shards,tasks", [("targeted", "4", 4), ("full", "5", 0)])
def test_actions_adapter_keeps_scope_and_three_repeat_budget(monkeypatch, scope, shards, tasks):
    monkeypatch.syspath_prepend(str(ROOT / "eval"))
    args = importlib.import_module("run_external_actions").arguments({"EVAL_SCOPE": scope, "EVAL_SHARD": "0"})
    assert args[args.index("--runs") + 1] == "3"
    assert args[args.index("--shards") + 1] == shards
    assert args.count("--task") == tasks
    with pytest.raises(ValueError):
        importlib.import_module("run_external_actions").arguments({"EVAL_SCOPE": scope, "EVAL_SHARD": "99"})
