"""Render inspectable evaluation results; unspecified monetary cost stays unknown."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics


def write_report(report: dict, output: Path) -> None:
    config, summary, records = report["config"], report["summary"], report["records"]
    scripted = config.get("evidence_type") == "scripted" or "FakeLLM" in str(summary.get("model"))
    input_price, output_price = config.get("input_price_per_million"), config.get("output_price_per_million")
    costs = []
    for record in records:
        usage = (record.get("agent") or {}).get("token_usage")
        if usage and input_price is not None and output_price is not None:
            costs.append((usage["prompt_tokens"] * input_price + usage["completion_tokens"] * output_price) / 1_000_000)
    cost = f"{statistics.mean(costs):.6f}" if costs and not scripted else "未测 / 不适用"
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["# RepoPilot Evaluation Report", "",
        "证据类型：" + ("**脚本化工程验证；不代表真实模型修复成功率。**" if scripted else "真实模型运行；仅适用于本报告任务集和配置。"), "",
        "配置：`" + json.dumps({k: config.get(k) for k in ("runtime", "tool_backend", "retrieval_mode", "reflection", "memory")}, ensure_ascii=False) + "`", "",
        "源码摘要：`" + config.get("source_sha256", "not recorded") + "`。", "",
        "| 指标 | 数值 |", "| --- | --- |",
        f"| 任务数 / 运行数 | {summary['task_count']} / {summary['runs']} |",
        f"| Task Success Rate（隐藏复测通过且 Agent 完成） | {summary['resolved_runs']}/{summary['runs']} = {summary['run_resolved_rate']:.1%} |",
        f"| Average Steps | {summary.get('average_steps')} |",
        f"| Average Token Count（chat） | {summary.get('average_total_tokens')} |",
        f"| Average Token Cost（chat；用户指定价格单位） | {cost} |",
        f"| Average Tool Call Number（含缓存/拒绝记录） | {summary.get('average_tool_calls')} |",
        f"| Average Executed Tool Calls | {summary.get('average_executed_tool_calls')} |",
        f"| 有完整 Agent 指标的运行数 | {summary.get('measured_agent_runs', len(records))} |", "",
        "金额只在真实模型和输入/输出单价均明确时估算；embedding 单独记录 Token，不混入 chat 费用。基础设施失败仍计入总运行分母，缺失的 Agent 步数/Token 不伪造为零。FakeLLM 不消耗模型 Token，0 不能解释为真实模型成本。", "",
        "## Failure Category", "", "```json", json.dumps(summary["failure_categories"], ensure_ascii=False, indent=2), "```", "",
        "## 逐任务证据", "", "| 任务 | 次数 | 结果 | 步数 | Token | 工具记录 | 失败类别 |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in records:
        agent = row.get("agent") or {}
        lines.append("| " + " | ".join(cell(value) for value in (
            row["task_id"], row["run"], "通过" if row["resolved"] else "失败", agent.get("steps", "缺失"),
            agent.get("token_usage", {}).get("total_tokens", "缺失"), agent.get("tool_calls", "缺失"),
            row.get("failure_category") or "—")) + " |")
    lines += ["", "评分流程：复制干净仓库 → 确认原始测试失败 → Agent 修复 → 恢复评分方拥有的测试 → 注入隐藏测试 → 独立复测。",
              "不向真实模型暴露 scripted_fixes 或隐藏测试。长期记忆在临时副本内隔离，不跨评测任务传播参考修复。", ""]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    write_report(json.loads(args.input.read_text(encoding="utf-8")), args.output or args.input.with_suffix(".md"))


if __name__ == "__main__":
    main()
