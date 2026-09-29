"""Evaluate the real model on a disposable Demo and export public-safe diagnostics."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.llm.openai_compatible import OpenAICompatibleLLM


ROOT = Path(__file__).resolve().parents[1]
TASK = json.loads((ROOT / "eval/tasks.json").read_text(encoding="utf-8"))[0]


def command(args: list[str], repo: Path, timeout: int = 90) -> dict:
    result = subprocess.run(args, cwd=repo, capture_output=True, text=True,
                            errors="replace", timeout=timeout)
    return {"exit_code": result.returncode, "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:]}


class ObservedLLM:
    def __init__(self, inner):
        self.inner = inner
        self.calls: list[dict] = []

    def chat(self, system: str, user: str):
        started = time.monotonic()
        call: dict = {"number": len(self.calls) + 1}
        try:
            response = self.inner.chat(system, user)
            call.update({"response": response.content[:12000],
                         "prompt_tokens": response.prompt_tokens,
                         "completion_tokens": response.completion_tokens})
            return response
        except Exception as exc:
            call["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            call["duration_seconds"] = round(time.monotonic() - started, 3)
            self.calls.append(call)


def redact(value, secret: str):
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, secret) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake", action="store_true", help="validate this reporting path without an API key")
    args = parser.parse_args()
    settings = Settings.load()
    result_path = ROOT / "eval/results" / ("actions-fake-local.json" if args.fake else "actions-qwen.json")
    report: dict = {"task": TASK["task"], "model": "scripted FakeLLM" if args.fake else settings.llm_model,
                    "expected_files": TASK["expected_files"], "success": False}
    exit_code = 1
    try:
        if not args.fake and not settings.llm_api_key:
            raise ValueError("Missing DASHSCOPE_API_KEY repository secret (LLM_API_KEY)")
        with tempfile.TemporaryDirectory(prefix="repopilot-actions-") as temp:
            repo = Path(temp) / "demo"
            shutil.copytree(ROOT / TASK["repo"], repo)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.email=eval@example.invalid",
                            "-c", "user.name=Eval", "commit", "-qm", "baseline"], check=True)
            report["baseline_test"] = command([sys.executable, "-m", "pytest", "-q"], repo)
            if report["baseline_test"]["exit_code"] == 0:
                raise RuntimeError("Demo baseline unexpectedly passes; no bug to evaluate")

            model = ObservedLLM(FakeLLM(demo_responses()) if args.fake else OpenAICompatibleLLM(settings))
            try:
                state = RepoPilot(repo, model, settings, executor="local", approval="auto").run(TASK["task"])
                report["agent"] = {
                    "status": state.status, "summary": state.summary, "error": state.error,
                    "plan": state.plan.model_dump() if state.plan else None,
                    "steps": state.current_step, "test_status": state.test_status,
                    "changed_files": state.changed_files, "tool_history": state.tool_history,
                    "token_usage": state.token_usage, "duration_seconds": state.duration_seconds,
                    "final_diff": state.final_diff,
                }
            finally:
                report["model_calls"] = model.calls

            report["final_test"] = command([sys.executable, "-m", "pytest", "-q"], repo)
            report["git_status"] = command(["git", "status", "--short"], repo)["stdout"]
            report["git_diff"] = command(["git", "diff", "--"], repo)["stdout"]
            report["success"] = (
                state.status == "completed"
                and report["final_test"]["exit_code"] == 0
                and set(state.changed_files) == set(TASK["expected_files"])
                and report["git_status"].strip() == "M app/users.py"
            )
            exit_code = 0 if report["success"] else 1
    except Exception as exc:
        report["runner_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(redact(report, os.getenv("LLM_API_KEY", "")),
                                          ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"success={report['success']} model={report['model']} diagnostics={result_path}")
        if "runner_error" in report:
            print(f"runner_error={redact(report['runner_error'], os.getenv('LLM_API_KEY', ''))}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
