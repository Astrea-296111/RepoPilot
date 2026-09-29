"""Reproducible, key-free workflow evaluation on fresh temporary copies."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM


def main():
    root = Path(__file__).resolve().parents[1]
    results = []
    for task in json.loads((root / "eval/tasks.json").read_text(encoding="utf-8")):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            shutil.copytree(root / task["repo"], repo)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.email=eval@example.invalid", "-c", "user.name=Eval", "commit", "-qm", "baseline"], check=True)
            before = subprocess.run(task["test_command"], shell=True, cwd=repo, capture_output=True)
            started = time.monotonic()
            state = RepoPilot(repo, FakeLLM(demo_responses()), Settings(), executor="local", approval="auto").run(task["task"])
            after = subprocess.run(task["test_command"], shell=True, cwd=repo, capture_output=True)
            results.append({"id": task["id"], "task_success": before.returncode != 0 and state.status == "completed" and after.returncode == 0 and set(state.changed_files) == set(task["expected_files"]),
                            "baseline_exit_code": before.returncode, "final_exit_code": after.returncode,
                            "steps": state.current_step, "tool_calls": len(state.tool_history),
                            "duration_seconds": round(time.monotonic()-started, 3),
                            "changed_files": state.changed_files, "prompt_tokens": state.token_usage["prompt_tokens"],
                            "completion_tokens": state.token_usage["completion_tokens"], "model": "scripted FakeLLM"})
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not all(item["task_success"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__": main()
