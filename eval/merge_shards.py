"""Merge benchmark shard JSONs, rejecting duplicates and incomplete task repeats."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def merge(paths: list[Path], expected_task_count: int | None = None) -> dict:
    if not paths:
        raise ValueError("provide at least one shard")
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    first = reports[0]
    runner = first["summary"]["runner"]
    model = first["summary"]["model"]
    config = first.get("config")
    if not config or runner not in {"agent", "one-shot"}:
        raise ValueError("shards require a supported runner and recorded config")
    runs_per_task = config["runs_per_task"]
    if not isinstance(runs_per_task, int) or runs_per_task < 1:
        raise ValueError("invalid runs_per_task")

    records: dict[tuple[str, int], dict] = {}
    for path, report in zip(paths, reports):
        summary = report["summary"]
        if summary["runner"] != runner or summary["model"] != model or report.get("config") != config:
            raise ValueError(f"incompatible shard: {path}")
        if not report["records"]:
            raise ValueError(f"empty shard: {path}")
        for record in report["records"]:
            key = (record["task_id"], record["run"])
            if key in records:
                raise ValueError(f"duplicate task/run: {key}")
            records[key] = record

    tasks = {task_id for task_id, _ in records}
    if expected_task_count is not None and len(tasks) != expected_task_count:
        raise ValueError(f"expected {expected_task_count} tasks, found {len(tasks)}")
    expected = set(range(1, runs_per_task + 1))
    for task_id in tasks:
        actual = {run for name, run in records if name == task_id}
        if actual != expected:
            raise ValueError(f"incomplete repeats for {task_id}: {sorted(actual)}")

    ordered = [records[key] for key in sorted(records)]
    if runner == "agent":
        from run_benchmark import summarize
    else:
        from run_one_shot import summarize
    return {"summary": summarize(ordered, model), "records": ordered, "config": config,
            "source_shards": [path.name for path in paths]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="+", type=Path)
    parser.add_argument("--expected-task-count", type=int)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = merge(args.shards, args.expected_task_count)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"merged={args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
