"""Measure file recall against the benchmark's known scripted fix paths.

These paths are one valid solution, not an exhaustive set of possible fixes.
Use this offline diagnostic to compare context selection, never as model input.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

from repopilot.context.repo_map import build_repo_map
from repopilot.context.retrieval import retrieve, retrieve_with_imports


ROOT = Path(__file__).resolve().parents[1]


def measure() -> dict:
    tasks = json.loads((ROOT / "eval" / "benchmark_tasks.json").read_text(encoding="utf-8"))
    fixes = json.loads((ROOT / "eval" / "scripted_fixes.json").read_text(encoding="utf-8"))
    rows = []
    for task in tasks:
        repo = ROOT / task["repo"]
        entries = build_repo_map(repo)
        targets = {patch["path"] for patch in fixes[task["id"]]["patches"]}
        if not targets or any(not (repo / path).is_file() for path in targets):
            raise ValueError(f"invalid scripted fix paths: {task['id']}")
        row = {"task_id": task["id"], "difficulty": task["difficulty"],
               "reference_fix_paths": sorted(targets)}
        for mode, ranking in (("retrieved", retrieve(repo, entries, task["task"], top_k=4)),
                              ("graph", retrieve_with_imports(repo, entries, task["task"], top_k=4))):
            paths = [path for path, _ in ranking]
            row[mode] = {"paths": paths,
                         "reference_paths_found": sorted(targets.intersection(paths)),
                         "all_reference_paths_found": targets.issubset(paths),
                         "source_chars": sum(min(len((repo / path).read_text(encoding="utf-8", errors="replace")), 7000)
                                             for path in paths)}
        rows.append(row)
    summary = {}
    for mode in ("retrieved", "graph"):
        summary[mode] = {"tasks": len(rows),
                         "hit_all": sum(row[mode]["all_reference_paths_found"] for row in rows),
                         "mean_source_chars": round(statistics.mean(row[mode]["source_chars"] for row in rows), 1),
                         "mean_selected_files": round(statistics.mean(len(row[mode]["paths"]) for row in rows), 2)}
    return {"reference": "scripted_fixes.json paths (one known solution per task)",
            "top_k": 4, "summary": summary, "tasks": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = measure()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"diagnostics={args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
