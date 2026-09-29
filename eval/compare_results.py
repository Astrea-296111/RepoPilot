"""Compare paired Agent and one-shot benchmark result JSON files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent")
    parser.add_argument("oneshot")
    parser.add_argument("--json-out", default="eval/results/comparison.json")
    parser.add_argument("--md-out", default="eval/results/comparison.md")
    args = parser.parse_args()

    agent = json.loads(Path(args.agent).read_text(encoding="utf-8"))
    one = json.loads(Path(args.oneshot).read_text(encoding="utf-8"))
    a_records = {(r["task_id"], r["run"]): r for r in agent["records"]}
    o_records = {(r["task_id"], r["run"]): r for r in one["records"]}
    if len(a_records) != len(agent["records"]) or len(o_records) != len(one["records"]):
        raise SystemExit("duplicate task/run records")
    if set(a_records) != set(o_records):
        raise SystemExit(f"unpaired records: agent-only={len(set(a_records)-set(o_records))}, "
                         f"oneshot-only={len(set(o_records)-set(a_records))}")
    keys = sorted(a_records)
    if not keys:
        raise SystemExit("no paired records")
    a_config, o_config = agent.get("config"), one.get("config")
    if bool(a_config) != bool(o_config):
        raise SystemExit("one report is missing model configuration")
    if a_config:
        shared = ("model", "base_url", "reasoning_effort", "stream", "timeout_seconds", "runs_per_task")
        mismatched = [name for name in shared if a_config.get(name) != o_config.get(name)]
        if mismatched:
            raise SystemExit(f"model configuration differs: {', '.join(mismatched)}")

    rows = []
    counts = {"agent_only": 0, "oneshot_only": 0, "both": 0, "neither": 0}
    comparable_counts = {name: 0 for name in counts}
    excluded = ("model_timeout", "model_transport_failure", "environment_failure", "invalid_baseline")
    for key in keys:
        a = a_records[key]
        o = o_records[key]
        ar = bool(a.get("resolved"))
        orun = bool(o.get("resolved"))
        if ar and orun:
            outcome = "both"
        elif ar:
            outcome = "agent_only"
        elif orun:
            outcome = "oneshot_only"
        else:
            outcome = "neither"
        counts[outcome] += 1
        if a.get("failure_category") not in excluded and o.get("failure_category") not in excluded:
            comparable_counts[outcome] += 1
        a_info = a.get("agent") or {}
        o_call = o.get("model_call") or {}
        rows.append({
            "task_id": key[0],
            "run": key[1],
            "difficulty": a.get("difficulty"),
            "category": a.get("category"),
            "outcome": outcome,
            "agent_resolved": ar,
            "oneshot_resolved": orun,
            "agent_tokens": (a_info.get("token_usage") or {}).get("total_tokens"),
            "oneshot_tokens": o_call.get("total_tokens"),
            "agent_duration_seconds": a_info.get("duration_seconds"),
            "oneshot_duration_seconds": o_call.get("duration_seconds"),
            "agent_failure": a.get("failure_category"),
            "oneshot_failure": o.get("failure_category"),
            "oneshot_context_files": (o.get("context") or {}).get("file_count"),
            "oneshot_prompt_chars": (o.get("context") or {}).get("prompt_chars"),
        })

    a_summary = agent["summary"]
    o_summary = one["summary"]
    comparison = {
        "suite": a_summary.get("suite"),
        "model": a_summary.get("model"),
        "paired_runs": len(keys),
        "paired_outcomes": counts,
        "transport_excluded_pairs": len(keys) - sum(comparable_counts.values()),
        "non_transport_paired_outcomes": comparable_counts,
        "configuration": {"shared": {key: a_config.get(key) for key in shared},
                          "agent_retrieval_mode": a_config.get("retrieval_mode", "lexical"),
                          "oneshot_context_mode": o_config.get("context_mode")} if a_config else None,
        "agent": {
            "resolved_runs": a_summary["resolved_runs"],
            "runs": a_summary["runs"],
            "resolved_rate": a_summary["run_resolved_rate"],
            "median_total_tokens": a_summary.get("median_total_tokens"),
            "median_duration_seconds": a_summary.get("median_duration_seconds"),
        },
        "oneshot": {
            "resolved_runs": o_summary["resolved_runs"],
            "runs": o_summary["runs"],
            "resolved_rate": o_summary["run_resolved_rate"],
            "median_total_tokens": o_summary.get("median_total_tokens"),
            "median_duration_seconds": o_summary.get("median_duration_seconds"),
        },
        "resolved_rate_delta_agent_minus_oneshot": round(
            a_summary["run_resolved_rate"] - o_summary["run_resolved_rate"], 4
        ),
        "records": rows,
    }

    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# RepoPilot Agent vs One-shot",
        "",
        f"- Model: {comparison['model']}",
        f"- Paired runs: {len(keys)}",
        f"- Agent resolved: {a_summary['resolved_runs']}/{a_summary['runs']} ({pct(a_summary['run_resolved_rate'])})",
        f"- One-shot resolved: {o_summary['resolved_runs']}/{o_summary['runs']} ({pct(o_summary['run_resolved_rate'])})",
        f"- Delta (Agent - one-shot): {comparison['resolved_rate_delta_agent_minus_oneshot'] * 100:+.1f} pp",
        f"- Paired outcomes: agent-only={counts['agent_only']}, one-shot-only={counts['oneshot_only']}, both={counts['both']}, neither={counts['neither']}",
        f"- Pairs excluded from behavior comparison (transport/runner): {comparison['transport_excluded_pairs']}",
        f"- One-shot context: {o_config.get('context_mode') if o_config else 'unrecorded'}",
        f"- Agent retrieval: {a_config.get('retrieval_mode', 'lexical') if a_config else 'unrecorded'}",
        f"- Median tokens: Agent={a_summary.get('median_total_tokens')}, One-shot={o_summary.get('median_total_tokens')}",
        f"- Median duration: Agent={a_summary.get('median_duration_seconds')}s, One-shot={o_summary.get('median_duration_seconds')}s",
        "",
        "| Task | Run | Difficulty | Outcome | Agent | One-shot | Agent tokens | One-shot tokens |",
        "| --- | ---: | --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['task_id']} | {row['run']} | {row['difficulty']} | {row['outcome']} | "
            f"{'✅' if row['agent_resolved'] else '❌'} | {'✅' if row['oneshot_resolved'] else '❌'} | "
            f"{row['agent_tokens']} | {row['oneshot_tokens']} |"
        )
    md_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in comparison.items() if k != "records"}, ensure_ascii=False, indent=2))
    print(f"markdown={md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
