"""Run the RepoPilot mini benchmark with hidden regression tests and aggregate metrics."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import time

from repopilot.agent.agent import RepoPilot
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.llm.openai_compatible import OpenAICompatibleLLM


ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "eval" / "benchmark_tasks.json"
FIXES_PATH = ROOT / "eval" / "scripted_fixes.json"


def command(command_text: str, repo: Path, timeout: int = 120) -> dict:
    result = subprocess.run(
        command_text,
        shell=True,
        cwd=repo,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
    }


class ObservedLLM:
    def __init__(self, inner):
        self.inner = inner
        self.calls: list[dict] = []

    def chat(self, system: str, user: str):
        started = time.monotonic()
        call: dict = {"number": len(self.calls) + 1}
        try:
            response = self.inner.chat(system, user)
            call.update({
                "response": response.content[:12000],
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
            })
            return response
        except Exception as exc:
            call["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            call["duration_seconds"] = round(time.monotonic() - started, 3)
            self.calls.append(call)


def scripted_responses(task: dict, fix: dict) -> list[str]:
    plan = {
        "goal": task["task"],
        "suspected_files": [fix["path"]],
        "steps": ["apply known harness patch", "verify tests"],
        "test_command": task["test_command"],
    }
    patch = {
        "type": "tool",
        "tool": "apply_patch",
        "arguments": {
            "path": fix["path"],
            "old_text": fix["old_text"],
            "new_text": fix["new_text"],
        },
        "reason": "deterministic harness validation",
    }
    final = {
        "type": "final",
        "summary": "scripted benchmark fix applied",
        "tests": "program-side final verification",
        "changed_files": [fix["path"]],
    }
    return [json.dumps(item, ensure_ascii=False) for item in (plan, patch, final)]


def git_changed_files(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.replace("\\", "/"))
    return files


def protected_modified(changed_files: list[str], protected_paths: list[str]) -> list[str]:
    normalized = [path.rstrip("/") + "/" for path in protected_paths]
    return [
        changed for changed in changed_files
        if any(changed == prefix[:-1] or changed.startswith(prefix) for prefix in normalized)
    ]


def diff_stats(repo: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["git", "-C", str(repo), "diff", "--numstat"],
        capture_output=True,
        text=True,
        check=True,
    )
    added = deleted = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0])
            deleted += int(parts[1])
    return added, deleted


def classify_failure(record: dict) -> str | None:
    if record.get("resolved"):
        return None
    if record.get("runner_error"):
        return "environment_failure"
    if record.get("baseline_test", {}).get("exit_code") == 0:
        return "invalid_baseline"
    if record.get("protected_modified"):
        return "protected_test_modified"
    agent = record.get("agent") or {}
    error = (agent.get("error") or "").lower()
    if "loop_detection" in error or "max_steps" in error:
        return "loop_failure"
    if "无效 json" in error or "json" in error and agent.get("status") == "failed":
        return "protocol_failure"
    if agent.get("status") != "completed":
        return "agent_failure"
    if record.get("hidden_test", {}).get("exit_code") != 0:
        return "behavior_failure"
    return "evaluation_failure"


def inject_hidden_test(task: dict, repo: Path) -> Path:
    source = ROOT / task["hidden_test"]
    target = repo / "tests" / "test_hidden_eval.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def run_one(task: dict, run_number: int, *, fake: bool, settings: Settings, fixes: dict) -> dict:
    record: dict = {
        "task_id": task["id"],
        "run": run_number,
        "category": task["category"],
        "difficulty": task["difficulty"],
        "resolved": False,
    }
    try:
        with tempfile.TemporaryDirectory(prefix=f"repopilot-{task['id']}-") as temp:
            repo = Path(temp) / "repo"
            shutil.copytree(ROOT / task["repo"], repo)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run([
                "git", "-C", str(repo), "-c", "user.email=eval@example.invalid",
                "-c", "user.name=Eval", "commit", "-qm", "benchmark baseline",
            ], check=True)

            record["baseline_test"] = command(task["test_command"], repo)
            if record["baseline_test"]["exit_code"] == 0:
                raise RuntimeError("benchmark baseline unexpectedly passes")

            inner = FakeLLM(scripted_responses(task, fixes[task["id"]])) if fake else OpenAICompatibleLLM(settings)
            model = ObservedLLM(inner)
            state = RepoPilot(repo, model, settings, executor="local", approval="auto").run(task["task"])
            changed = git_changed_files(repo)
            protected = protected_modified(changed, task.get("protected_paths", []))
            added, deleted = diff_stats(repo)

            record["agent"] = {
                "status": state.status,
                "summary": state.summary,
                "error": state.error,
                "plan": state.plan.model_dump() if state.plan else None,
                "steps": state.current_step,
                "test_status": state.test_status,
                "tool_calls": len(state.tool_history),
                "changed_files": changed,
                "token_usage": state.token_usage,
                "duration_seconds": state.duration_seconds,
            }
            record["model_calls"] = model.calls
            record["protected_modified"] = protected
            record["diff_stats"] = {"added_lines": added, "deleted_lines": deleted}

            inject_hidden_test(task, repo)
            record["hidden_test"] = command(task["test_command"], repo)
            record["resolved"] = (
                state.status == "completed"
                and not protected
                and record["hidden_test"]["exit_code"] == 0
            )
    except Exception as exc:
        record["runner_error"] = f"{type(exc).__name__}: {exc}"
    record["failure_category"] = classify_failure(record)
    return record


def metric(values: list[float | int]) -> float | None:
    return round(float(statistics.median(values)), 3) if values else None


def summarize(records: list[dict], model_name: str) -> dict:
    first_runs = [item for item in records if item["run"] == 1]
    resolved = [item for item in records if item["resolved"]]
    categories: dict[str, dict] = {}
    by_category: dict[str, list[dict]] = defaultdict(list)
    for item in records:
        by_category[item["category"]].append(item)
    for name, items in sorted(by_category.items()):
        categories[name] = {
            "runs": len(items),
            "resolved": sum(1 for item in items if item["resolved"]),
        }

    agent_records = [item["agent"] for item in records if item.get("agent")]
    token_totals = [a["token_usage"]["total_tokens"] for a in agent_records]
    return {
        "suite": "RepoPilot Mini Benchmark v2",
        "model": model_name,
        "task_count": len({item["task_id"] for item in records}),
        "runs": len(records),
        "resolved_runs": len(resolved),
        "run_resolved_rate": round(len(resolved) / len(records), 4) if records else 0,
        "first_run_resolved": sum(1 for item in first_runs if item["resolved"]),
        "first_run_tasks": len(first_runs),
        "first_run_resolved_rate": round(
            sum(1 for item in first_runs if item["resolved"]) / len(first_runs), 4
        ) if first_runs else 0,
        "median_steps": metric([a["steps"] for a in agent_records]),
        "median_tool_calls": metric([a["tool_calls"] for a in agent_records]),
        "median_total_tokens": metric(token_totals),
        "median_duration_seconds": metric([
            a["duration_seconds"] for a in agent_records if a["duration_seconds"] is not None
        ]),
        "failure_categories": dict(Counter(
            item["failure_category"] for item in records if item["failure_category"]
        )),
        "categories": categories,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake", action="store_true", help="Use deterministic scripted fixes; no API key")
    parser.add_argument("--runs", type=int, default=1, help="Runs per task")
    parser.add_argument("--limit", type=int, default=0, help="Only run the first N tasks (0 = all)")
    parser.add_argument("--task", action="append", default=[], help="Only run selected task id; repeatable")
    parser.add_argument("--require-all", action="store_true", help="Exit non-zero when any task is unresolved")
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error("--runs must be between 1 and 10")

    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    if args.task:
        wanted = set(args.task)
        tasks = [task for task in tasks if task["id"] in wanted]
    if args.limit:
        tasks = tasks[:args.limit]
    if not tasks:
        parser.error("no benchmark tasks selected")

    fixes = json.loads(FIXES_PATH.read_text(encoding="utf-8"))
    settings = Settings.load()
    if not args.fake and (not settings.llm_api_key or not settings.llm_model):
        raise SystemExit("LLM_API_KEY and LLM_MODEL are required for real-model benchmark")

    model_name = "scripted FakeLLM" if args.fake else settings.llm_model
    records = [
        run_one(task, run_number, fake=args.fake, settings=settings, fixes=fixes)
        for task in tasks
        for run_number in range(1, args.runs + 1)
    ]
    report = {
        "summary": summarize(records, model_name),
        "records": records,
    }

    suffix = "fake" if args.fake else "qwen"
    output = ROOT / "eval" / "results" / f"benchmark-{suffix}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"diagnostics={output}")
    infrastructure_failures = [
        item for item in records
        if item.get("runner_error") or item.get("failure_category") == "invalid_baseline"
    ]
    if infrastructure_failures:
        return 2
    if args.require_all and not all(item["resolved"] for item in records):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
