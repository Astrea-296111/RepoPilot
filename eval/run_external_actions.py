"""Explicit paid Actions scope adapter; task definitions and graders stay untouched."""
import os
from pathlib import Path
import subprocess
import sys

TARGETED_TASK_IDS = ("boltons_research", "more_predicate_sentinel", "slugify_hex", "slugify_truncation")


def arguments(environment: dict) -> list[str]:
    """Build validated fixed-budget arguments without reading model credentials."""
    scope = environment.get("EVAL_SCOPE", "targeted")
    runtime = environment.get("EVAL_RUNTIME", "custom")
    mode = environment.get("EVAL_MODE", "agent")
    if scope not in {"targeted", "full"} or runtime not in {"custom", "langgraph"} or mode not in {"agent", "oneshot"}:
        raise ValueError("Invalid evaluation scope, runtime or mode")
    shards = 5 if scope == "full" else 4
    shard = int(environment.get("EVAL_SHARD", "0"))
    if not 0 <= shard < shards:
        raise ValueError("Shard outside selected scope")
    args = ["--mode", mode, "--runtime", runtime, "--runs", "3", "--shard", str(shard), "--shards", str(shards)]
    if scope == "targeted":
        for task in TARGETED_TASK_IDS:
            args.extend(["--task", task])
    return args


if __name__ == "__main__":
    args = arguments(os.environ)
    print("Fixed evaluation arguments:", " ".join(args), flush=True)
    subprocess.run([sys.executable, str(Path(__file__).with_name("run_external.py")), *args],
                   check=True, timeout=3900)
