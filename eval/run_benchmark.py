"""Run the RepoPilot multi-task benchmark with hidden regression tests."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
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
from model_retry import RetryingLLM


ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "eval" / "benchmark_tasks.json"
FIXES_PATH = ROOT / "eval" / "scripted_fixes.json"


def command(command_text: str, repo: Path, timeout: int = 120) -> dict:
    result = subprocess.run(
        command_text, shell=True, cwd=repo, capture_output=True, text=True,
        errors="replace", timeout=timeout,
    )
    return {"exit_code": result.returncode, "stdout": result.stdout[-12000:], "stderr": result.stderr[-12000:]}


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
    patches = fix["patches"]
    responses = [json.dumps({
        "goal": task["task"],
        "suspected_files": sorted({item["path"] for item in patches}),
        "steps": ["apply known harness patch", "verify tests"],
        "test_command": task["test_command"],
    }, ensure_ascii=False)]
    for patch in patches:
        responses.append(json.dumps({
            "type": "tool", "tool": "apply_patch", "arguments": patch,
            "reason": "deterministic harness validation",
        }, ensure_ascii=False))
    responses.append(json.dumps({
        "type": "final", "summary": "scripted benchmark fix applied",
        "tests": "program-side final verification",
        "changed_files": sorted({item["path"] for item in patches}),
    }, ensure_ascii=False))
    return responses


def prepare_repo(task: dict, temp: str) -> Path:
    repo = Path(temp) / "repo"
    shutil.copytree(ROOT / task["repo"], repo)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(repo), "-c", "user.email=eval@example.invalid",
        "-c", "user.name=Eval", "commit", "-qm", "benchmark baseline",
    ], check=True)
    return repo


def git_changed_files(repo: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True)
    files = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.replace("\\", "/"))
    return files


def protected_modified(changed_files: list[str], protected_paths: list[str]) -> list[str]:
    prefixes = [path.rstrip("/") + "/" for path in protected_paths]
    return [changed for changed in changed_files if any(changed == prefix[:-1] or changed.startswith(prefix) for prefix in prefixes)]


def restore_protected_paths(repo: Path, protected_paths: list[str]) -> None:
    """Discard agent changes to grader-owned paths before final evaluation."""
    for path in protected_paths:
        subprocess.run(
            ["git", "-C", str(repo), "restore", "--source=HEAD", "--staged", "--worktree", "--", path],
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            ["git", "-C", str(repo), "clean", "-fd", "--", path],
            capture_output=True,
            text=True,
            check=True,
        )

def diff_stats(repo: Path) -> tuple[int, int]:
    result = subprocess.run(["git", "-C", str(repo), "diff", "--numstat"], capture_output=True, text=True, check=True)
    added = deleted = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0]); deleted += int(parts[1])
    return added, deleted


def inject_hidden_test(task: dict, repo: Path) -> None:
    source = ROOT / task["hidden_test"]
    target = repo / "tests" / "test_hidden_eval.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def classify_failure(record: dict) -> str | None:
    if record.get("resolved"): return None
    if record.get("runner_error"): return "environment_failure"
    if record.get("baseline_test", {}).get("exit_code") == 0: return "invalid_baseline"
    agent = record.get("agent") or {}
    error = (agent.get("error") or "").lower()
    if "请求超时" in error: return "model_timeout"
    if "模型服务" in error: return "model_transport_failure"
    if "loop_detection" in error or "max_steps" in error: return "loop_failure"
    if ("无效 json" in error or "json" in error) and agent.get("status") == "failed": return "protocol_failure"
    if agent.get("status") != "completed": return "agent_failure"
    if record.get("hidden_test", {}).get("exit_code") != 0: return "behavior_failure"
    return "evaluation_failure"


def run_one(task: dict, run_number: int, *, fake: bool, settings: Settings, fixes: dict, runtime: str = "custom") -> dict:
    record = {"task_id": task["id"], "run": run_number, "category": task["category"], "difficulty": task["difficulty"], "resolved": False}
    try:
        with tempfile.TemporaryDirectory(prefix=f"repopilot-{task['id']}-") as temp:
            repo = prepare_repo(task, temp)
            record["baseline_test"] = command(task["test_command"], repo)
            if record["baseline_test"]["exit_code"] == 0:
                raise RuntimeError("benchmark baseline unexpectedly passes")

            retrying = None
            if fake:
                inner = FakeLLM(scripted_responses(task, fixes[task["id"]]))
            else:
                retrying = RetryingLLM(OpenAICompatibleLLM(settings))
                inner = retrying
            model = ObservedLLM(inner)
            state = RepoPilot(repo, model, settings, executor="local", approval="auto", runtime=runtime).run(task["task"])
            changed = git_changed_files(repo)
            protected = protected_modified(changed, task.get("protected_paths", []))
            added, deleted = diff_stats(repo)
            record["agent"] = {
                "status": state.status, "summary": state.summary, "error": state.error,
                "plan": state.plan.model_dump() if state.plan else None,
                "steps": state.current_step, "test_status": state.test_status,
                "tool_calls": len(state.tool_history), "changed_files": changed,
                "executed_tool_calls": sum(h.get("executed", True) for h in state.tool_history),
                "runtime": runtime,
                "retrieved_files": state.retrieved_files,
                "token_usage": state.token_usage, "duration_seconds": state.duration_seconds,
            }
            record["model_calls"] = model.calls
            record["llm_transport_retries"] = retrying.retries if retrying else 0
            record["protected_modified"] = protected
            record["diff_stats"] = {"added_lines": added, "deleted_lines": deleted}
            restore_protected_paths(repo, task.get("protected_paths", []))
            inject_hidden_test(task, repo)
            record["hidden_test"] = command(task["test_command"], repo)
            record["resolved"] = state.status == "completed" and record["hidden_test"]["exit_code"] == 0
    except Exception as exc:
        record["runner_error"] = f"{type(exc).__name__}: {exc}"
    record["failure_category"] = classify_failure(record)
    return record


def median(values):
    return round(float(statistics.median(values)), 3) if values else None


def summarize(records: list[dict], model_name: str) -> dict:
    first_runs = [item for item in records if item["run"] == 1]
    resolved = [item for item in records if item["resolved"]]
    by_category = defaultdict(list)
    by_difficulty = defaultdict(list)
    for item in records:
        by_category[item["category"]].append(item)
        by_difficulty[item["difficulty"]].append(item)
    agents = [item["agent"] for item in records if item.get("agent")]
    return {
        "suite": "RepoPilot Mini Benchmark v3",
        "runner": "agent",
        "model": model_name,
        "task_count": len({item["task_id"] for item in records}),
        "runs": len(records),
        "resolved_runs": len(resolved),
        "resolved_without_protected_edits": sum(item["resolved"] and not item.get("protected_modified") for item in records),
        "protected_edit_runs": sum(bool(item.get("protected_modified")) for item in records),
        "run_resolved_rate": round(len(resolved) / len(records), 4) if records else 0,
        "first_run_resolved": sum(1 for item in first_runs if item["resolved"]),
        "first_run_tasks": len(first_runs),
        "first_run_resolved_rate": round(sum(1 for item in first_runs if item["resolved"]) / len(first_runs), 4) if first_runs else 0,
        "median_steps": median([a["steps"] for a in agents]),
        "median_tool_calls": median([a["tool_calls"] for a in agents]),
        "median_total_tokens": median([a["token_usage"]["total_tokens"] for a in agents]),
        "median_duration_seconds": median([a["duration_seconds"] for a in agents if a["duration_seconds"] is not None]),
        "failure_categories": dict(Counter(item["failure_category"] for item in records if item["failure_category"])),
        "categories": {k: {"runs": len(v), "resolved": sum(i["resolved"] for i in v)} for k, v in sorted(by_category.items())},
        "difficulties": {k: {"runs": len(v), "resolved": sum(i["resolved"] for i in v)} for k, v in sorted(by_difficulty.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--runtime", choices=["custom", "langgraph"], default="custom")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10: parser.error("--runs must be between 1 and 10")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("shard index/count are invalid")
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    if args.task:
        wanted = set(args.task)
        unknown = wanted - {task["id"] for task in tasks}
        if unknown: parser.error(f"unknown task ids: {', '.join(sorted(unknown))}")
        tasks = [task for task in tasks if task["id"] in wanted]
    if args.limit: tasks = tasks[:args.limit]
    tasks = tasks[args.shard_index::args.shard_count]
    if not tasks: parser.error("no benchmark tasks selected")

    fixes = json.loads(FIXES_PATH.read_text(encoding="utf-8"))
    settings = Settings.load()
    if not args.fake and (not settings.llm_api_key or not settings.llm_model):
        raise SystemExit("LLM_API_KEY and LLM_MODEL are required")
    model_name = "scripted FakeLLM" if args.fake else settings.llm_model
    records = []
    total = len(tasks) * args.runs
    index = 0
    for task in tasks:
        for n in range(1, args.runs + 1):
            index += 1
            print(f"[agent] {index}/{total} start task={task['id']} run={n}", flush=True)
            item = run_one(task, n, fake=args.fake, settings=settings, fixes=fixes, runtime=args.runtime)
            records.append(item)
            details = item.get("agent") or {}
            tokens = (details.get("token_usage") or {}).get("total_tokens")
            print(
                f"[agent] {index}/{total} done task={task['id']} run={n} "
                f"resolved={item.get('resolved')} failure={item.get('failure_category')} "
                f"steps={details.get('steps')} tokens={tokens} duration={details.get('duration_seconds')}",
                flush=True,
            )
    report = {"summary": summarize(records, model_name), "records": records,
              "config": {"model": model_name, "base_url": settings.llm_base_url,
                         "reasoning_effort": settings.llm_reasoning_effort or "provider_default",
                         "stream": settings.llm_stream, "timeout_seconds": settings.llm_timeout_seconds,
                         "runs_per_task": args.runs, "retrieval_mode": "graph", "runtime": args.runtime}}
    suffix = "fake" if args.fake else "qwen"
    shard = f"-shard{args.shard_index}" if args.shard_count > 1 else ""
    runtime_suffix = "-langgraph" if args.runtime == "langgraph" else ""
    output = ROOT / "eval" / "results" / f"agent{runtime_suffix}-{suffix}{shard}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"diagnostics={output}")
    infra = [item for item in records if item.get("runner_error") or item.get("failure_category") == "invalid_baseline"]
    if infra: return 2
    if args.require_all and not all(item["resolved"] for item in records): return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
