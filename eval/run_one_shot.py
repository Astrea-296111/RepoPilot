"""Evaluate the same tasks with one model call and one patch batch (no Agent Loop)."""
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

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from repopilot.config import Settings
from repopilot.context.repo_map import build_repo_map, render_repo_map
from repopilot.context.retrieval import retrieve
from repopilot.llm.base import FakeLLM
from repopilot.llm.openai_compatible import OpenAICompatibleLLM
from model_retry import RetryingLLM
from repopilot.tools.base import Workspace
from repopilot.tools.filesystem import ApplyPatch


ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "eval" / "benchmark_tasks.json"
FIXES_PATH = ROOT / "eval" / "scripted_fixes.json"

SYSTEM = """You are a one-shot code repair baseline. You get one model call only.
Return exactly one JSON object, no Markdown:
{"patches":[{"path":"relative/path.py","old_text":"exact existing substring","new_text":"replacement"}],"summary":"short"}
Use 1-5 minimal patches. Do not modify tests. old_text must occur exactly once. Solve the stated task using the provided repo map, selected files, and failing test output."""


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    old_text: str = Field(min_length=1)
    new_text: str


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patches: list[Patch] = Field(min_length=1, max_length=5)
    summary: str


def command(command_text: str, repo: Path, timeout: int = 120) -> dict:
    result = subprocess.run(command_text, shell=True, cwd=repo, capture_output=True, text=True, errors="replace", timeout=timeout)
    return {"exit_code": result.returncode, "stdout": result.stdout[-12000:], "stderr": result.stderr[-12000:]}


def prepare_repo(task: dict, temp: str) -> Path:
    repo = Path(temp) / "repo"
    shutil.copytree(ROOT / task["repo"], repo)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=eval@example.invalid", "-c", "user.name=Eval", "commit", "-qm", "benchmark baseline"], check=True)
    return repo


def git_changed_files(repo: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True)
    files = []
    for line in result.stdout.splitlines():
        if line.strip():
            path = line[3:].strip()
            if " -> " in path: path = path.split(" -> ", 1)[1]
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

def inject_hidden_test(task: dict, repo: Path) -> None:
    source = ROOT / task["hidden_test"]
    target = repo / "tests" / "test_hidden_eval.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def diff_stats(repo: Path) -> tuple[int, int]:
    result = subprocess.run(["git", "-C", str(repo), "diff", "--numstat"], capture_output=True, text=True, check=True)
    added = deleted = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0]); deleted += int(parts[1])
    return added, deleted


def build_context(repo: Path, task: dict, baseline: dict) -> str:
    entries = build_repo_map(repo)
    repo_map = render_repo_map(entries, max_chars=9000)
    ranked = retrieve(repo, entries, task["task"], top_k=4)
    sections = []
    for path, score in ranked:
        content = (repo / path).read_text(encoding="utf-8", errors="replace")
        sections.append(f"FILE {path} score={score}\n{content[:7000]}")
    failing = (baseline.get("stdout", "") + "\n" + baseline.get("stderr", ""))[-7000:]
    return f"TASK:\n{task['task']}\n\nREPO MAP:\n{repo_map}\n\nFAILING TEST:\n{failing}\n\nSELECTED FILES:\n" + "\n\n".join(sections)


def fake_answer(fix: dict) -> str:
    return json.dumps({"patches": fix["patches"], "summary": "deterministic one-shot harness patch"}, ensure_ascii=False)


def classify(record: dict) -> str | None:
    if record.get("resolved"): return None
    if record.get("runner_error"): return "environment_failure"
    if record.get("baseline_test", {}).get("exit_code") == 0: return "invalid_baseline"
    if record.get("model_error"):
        return "model_timeout" if "请求超时" in record["model_error"] else "model_transport_failure"
    if record.get("protocol_error"): return "protocol_failure"
    if record.get("patch_error"): return "patch_failure"
    if record.get("hidden_test", {}).get("exit_code") != 0: return "behavior_failure"
    return "evaluation_failure"


def run_one(task: dict, run_number: int, *, fake: bool, settings: Settings, fixes: dict) -> dict:
    record = {"task_id": task["id"], "run": run_number, "category": task["category"], "difficulty": task["difficulty"], "resolved": False}
    try:
        with tempfile.TemporaryDirectory(prefix=f"oneshot-{task['id']}-") as temp:
            repo = prepare_repo(task, temp)
            baseline = command(task["test_command"], repo)
            record["baseline_test"] = baseline
            if baseline["exit_code"] == 0:
                raise RuntimeError("benchmark baseline unexpectedly passes")

            retrying = None
            if fake:
                inner = FakeLLM([fake_answer(fixes[task["id"]])])
            else:
                retrying = RetryingLLM(OpenAICompatibleLLM(settings))
                inner = retrying
            started = time.monotonic()
            try:
                response = inner.chat(SYSTEM, build_context(repo, task, baseline))
            except RuntimeError as exc:
                record["model_error"] = str(exc)
                record["llm_transport_retries"] = retrying.retries if retrying else 0
                record["failure_category"] = classify(record)
                return record
            duration = round(time.monotonic() - started, 3)
            record["model_call"] = {
                "response": response.content[:16000],
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.prompt_tokens + response.completion_tokens,
                "duration_seconds": duration,
            }
            record["llm_transport_retries"] = retrying.retries if retrying else 0
            try:
                answer = Answer.model_validate_json(response.content)
            except ValidationError as exc:
                record["protocol_error"] = str(exc)[:4000]
                record["failure_category"] = classify(record)
                return record

            workspace = Workspace(repo)
            patcher = ApplyPatch(workspace)
            for patch in answer.patches:
                try:
                    patcher.execute(patch.model_dump())
                except Exception as exc:
                    record["patch_error"] = f"{type(exc).__name__}: {exc}"
                    record["failure_category"] = classify(record)
                    return record

            changed = git_changed_files(repo)
            protected = protected_modified(changed, task.get("protected_paths", []))
            added, deleted = diff_stats(repo)
            record["summary"] = answer.summary
            record["patch_count"] = len(answer.patches)
            record["changed_files"] = changed
            record["protected_modified"] = protected
            record["diff_stats"] = {"added_lines": added, "deleted_lines": deleted}
            restore_protected_paths(repo, task.get("protected_paths", []))
            inject_hidden_test(task, repo)
            record["hidden_test"] = command(task["test_command"], repo)
            record["resolved"] = record["hidden_test"]["exit_code"] == 0
    except Exception as exc:
        record["runner_error"] = f"{type(exc).__name__}: {exc}"
    record["failure_category"] = classify(record)
    return record


def median(values):
    return round(float(statistics.median(values)), 3) if values else None


def summarize(records: list[dict], model_name: str) -> dict:
    first = [item for item in records if item["run"] == 1]
    resolved = [item for item in records if item["resolved"]]
    by_category = defaultdict(list); by_difficulty = defaultdict(list)
    for item in records:
        by_category[item["category"]].append(item); by_difficulty[item["difficulty"]].append(item)
    calls = [item["model_call"] for item in records if item.get("model_call")]
    return {
        "suite": "RepoPilot Mini Benchmark v3",
        "runner": "one-shot",
        "model": model_name,
        "task_count": len({i["task_id"] for i in records}),
        "runs": len(records),
        "resolved_runs": len(resolved),
        "run_resolved_rate": round(len(resolved)/len(records), 4) if records else 0,
        "first_run_resolved": sum(1 for i in first if i["resolved"]),
        "first_run_tasks": len(first),
        "first_run_resolved_rate": round(sum(1 for i in first if i["resolved"])/len(first), 4) if first else 0,
        "median_total_tokens": median([c["total_tokens"] for c in calls]),
        "median_duration_seconds": median([c["duration_seconds"] for c in calls]),
        "median_patch_count": median([i["patch_count"] for i in records if i.get("patch_count") is not None]),
        "failure_categories": dict(Counter(i["failure_category"] for i in records if i["failure_category"])),
        "categories": {k: {"runs": len(v), "resolved": sum(i["resolved"] for i in v)} for k,v in sorted(by_category.items())},
        "difficulties": {k: {"runs": len(v), "resolved": sum(i["resolved"] for i in v)} for k,v in sorted(by_difficulty.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake", action="store_true")
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
        wanted=set(args.task); tasks=[task for task in tasks if task["id"] in wanted]
    if args.limit: tasks=tasks[:args.limit]
    tasks=tasks[args.shard_index::args.shard_count]
    if not tasks: parser.error("no benchmark tasks selected")
    fixes=json.loads(FIXES_PATH.read_text(encoding="utf-8"))
    settings=Settings.load()
    if not args.fake and (not settings.llm_api_key or not settings.llm_model):
        raise SystemExit("LLM_API_KEY and LLM_MODEL are required")
    model_name="scripted FakeLLM" if args.fake else settings.llm_model
    records=[]
    total=len(tasks)*args.runs
    index=0
    for task in tasks:
        for n in range(1,args.runs+1):
            index+=1
            print(f"[one-shot] {index}/{total} start task={task['id']} run={n}", flush=True)
            item=run_one(task,n,fake=args.fake,settings=settings,fixes=fixes)
            records.append(item)
            call=item.get("model_call") or {}
            print(
                f"[one-shot] {index}/{total} done task={task['id']} run={n} "
                f"resolved={item.get('resolved')} failure={item.get('failure_category')} "
                f"tokens={call.get('total_tokens')} duration={call.get('duration_seconds')}",
                flush=True,
            )
    report={"summary":summarize(records,model_name),"records":records}
    suffix="fake" if args.fake else "qwen"
    shard=f"-shard{args.shard_index}" if args.shard_count > 1 else ""
    output=ROOT/"eval"/"results"/f"oneshot-{suffix}{shard}.json"
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report["summary"],ensure_ascii=False,indent=2))
    print(f"diagnostics={output}")
    infra=[i for i in records if i.get("runner_error") or i.get("failure_category")=="invalid_baseline"]
    if infra: return 2
    if args.require_all and not all(i["resolved"] for i in records): return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
