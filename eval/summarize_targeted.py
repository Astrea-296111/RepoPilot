"""Strict paired readout for the preregistered four-task risk scope, not a full score."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

from run_external_actions import TARGETED_TASK_IDS

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("suite_sha256", "model", "reasoning_effort", "stream", "max_steps", "max_context_chars", "runs", "shards", "timing_scope")


def median(values):
    values = list(values)
    return statistics.median(values) if values else None


def describe(records, mode):
    """Keep patch and terminal outcomes separate; count all attempted trials."""
    tokens = [r["token_usage"]["total_tokens"] for r in records if "token_usage" in r]
    errors = Counter(r.get("error", "") for r in records if r.get("error"))
    return {
        "trials": len(records), "resolved": sum(r["resolved"] for r in records),
        "completed_and_resolved": sum(r["resolved"] and (mode == "oneshot" or r.get("status") == "completed") for r in records),
        "loop_detection": errors["loop_detection"], "max_steps": errors["max_steps"],
        "protocol_failures": sum("JSON" in r.get("error", "") or "ValidationError" in r.get("error", "") for r in records),
        "terminal_errors": dict(errors),
        "median_steps": median(r["steps"] for r in records if "steps" in r),
        "median_tool_records": median(r["tool_calls"] for r in records if "tool_calls" in r),
        "median_executed_tool_calls": median(r.get("executed_tool_calls", r["tool_calls"]) for r in records if "tool_calls" in r),
        "median_tokens": median(tokens), "token_record_count": len(tokens), "total_tokens": sum(tokens),
        "median_end_to_end_seconds": median(r["end_to_end_seconds"] for r in records),
    }


def summarize(inputs):
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in inputs]
    docs = [d for d in docs if "records" in d]
    if len(docs) != 8:
        raise ValueError("Need exactly four shards per method for the targeted scope")
    config = {f: docs[0][f] for f in FIELDS}
    if config["runs"] != 3 or config["shards"] != 4:
        raise ValueError("Targeted design requires four shards and three repeats")
    seen, shard_keys = {}, set()
    runtimes = set()
    for doc in docs:
        if any(doc[f] != config[f] for f in FIELDS):
            raise ValueError("Configuration mismatch")
        if set(doc["task_ids"]) != set(TARGETED_TASK_IDS):
            raise ValueError("Target scope mismatch")
        shard_key = (doc["mode"], doc["shard"])
        if shard_key in shard_keys:
            raise ValueError("Duplicate shard")
        shard_keys.add(shard_key)
        if doc["mode"] == "agent":
            runtimes.add(doc["runtime"])
        for record in doc["records"]:
            key = (record["task_id"], record["run"], record["mode"])
            if key in seen:
                raise ValueError("Duplicate trial")
            seen[key] = record
    expected = {(task, run, mode) for task in TARGETED_TASK_IDS for run in (1, 2, 3) for mode in ("agent", "oneshot")}
    if set(seen) != expected or shard_keys != {(m, i) for m in ("agent", "oneshot") for i in range(4)} or len(runtimes) != 1:
        raise ValueError("Missing, extra or mixed-runtime targeted trials")
    config["runtime"] = runtimes.pop()
    methods = {mode: describe([r for (t, n, m), r in seen.items() if m == mode], mode) for mode in ("agent", "oneshot")}
    historical_path = ROOT / "eval/evidence/2026-09-30"
    manifest = json.loads((historical_path / "manifest.json").read_text(encoding="utf-8"))
    if manifest["configuration"]["suite_sha256"] != config["suite_sha256"]:
        raise ValueError("Frozen suite differs from the historical baseline")
    old = []
    for path in sorted((historical_path / "shards").glob("external-*.json")):
        old.extend(r for r in json.loads(path.read_text(encoding="utf-8")).get("records", []) if r["task_id"] in TARGETED_TASK_IDS)
    if {(r["task_id"], r["run"], r["mode"]) for r in old} != expected or len(old) != len(expected):
        raise ValueError("Historical targeted slice is incomplete or duplicated")
    by_task = [{"task_id": task, **{
        mode: describe([seen[(task, n, mode)] for n in (1, 2, 3)], mode) for mode in ("agent", "oneshot")}}
        for task in TARGETED_TASK_IDS]
    return {"scope": {"independent_tasks": 4, "repeats_per_task_per_method": 3, "trials": 24},
            "config": config, "methods": methods, "by_task": by_task,
            "historical_same_scope": {"commit": manifest["evaluated_commit"], "run_url": manifest["run_url"],
                                      "methods": {m: describe([r for r in old if r["mode"] == m], m) for m in ("agent", "oneshot")}},
            "limitations": ["Risk tasks selected from historical failures; this is not a representative full-suite success rate.",
                "Original 10-task full benchmark has not been rerun by this targeted execution.",
                "Runtime feedback and repeat/termination policies intentionally changed; task prompts, source files and scoring are frozen.",
                "Historical/current model aliases are mutable and runs are not contemporaneous; descriptive before/after only.",
                "Repeated trials share four tasks; do not treat 12 method trials as 12 independent bugs.",
                "tool_records includes reused/withheld observations; executed_tool_calls counts actual dispatches including verification, excluding denials/cache."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("eval/results/external-comparison.json"))
    args = parser.parse_args()
    report = summarize(sorted(args.input.rglob("external-*.json")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# RepoPilot 固定风险任务对照", "", "4 个历史 Bug ×3 次重复 ×2 种方法 =24 次真实试验。原全量分母不变。", "",
             "| 阶段 | 方法 | 补丁通过 | 正常结束并通过 | loop_detection | 步数中位数 | Token 中位数 | 端到端秒中位数 |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for stage, methods in (("历史同范围切片", report["historical_same_scope"]["methods"]), ("本轮 targeted", report["methods"])):
        for mode, values in methods.items():
            lines.append(f"| {stage} | {mode} | {values['resolved']}/{values['trials']} | {values['completed_and_resolved']}/{values['trials']} | {values['loop_detection']} | {values['median_steps']} | {values['median_tokens']} | {values['median_end_to_end_seconds']} |")
    lines += ["", "| 任务 | Agent 补丁/终态通过 | one-shot 通过 |", "|---|---:|---:|"]
    for row in report["by_task"]:
        lines.append(f"| {row['task_id']} | {row['agent']['resolved']}/3 ; {row['agent']['completed_and_resolved']}/3 | {row['oneshot']['resolved']}/3 |")
    lines += ["", *["- " + item for item in report["limitations"]]]
    args.output.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print(json.dumps(report["methods"], ensure_ascii=False))


if __name__ == "__main__":
    main()
