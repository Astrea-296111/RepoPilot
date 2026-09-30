# RepoPilot 固定风险任务对照

4 个历史 Bug ×3 次重复 ×2 种方法 =24 次真实试验。原全量分母不变。

| 阶段 | 方法 | 补丁通过 | 正常结束并通过 | loop_detection | 步数中位数 | Token 中位数 | 端到端秒中位数 |
|---|---|---:|---:|---:|---:|---:|---:|
| 历史同范围切片 | agent | 7/12 | 5/12 | 5 | 7.0 | 50781.0 | 187.4615 |
| 历史同范围切片 | oneshot | 10/12 | 10/12 | 0 | None | 6010.0 | 56.966499999999996 |
| 本轮 targeted | agent | 12/12 | 12/12 | 0 | 7.5 | 50297.5 | 154.86950000000002 |
| 本轮 targeted | oneshot | 7/12 | 7/12 | 0 | None | 6128.5 | 53.09 |

| 任务 | Agent 补丁/终态通过 | one-shot 通过 |
|---|---:|---:|
| boltons_research | 3/3 ; 3/3 | 1/3 |
| more_predicate_sentinel | 3/3 ; 3/3 | 3/3 |
| slugify_hex | 3/3 ; 3/3 | 1/3 |
| slugify_truncation | 3/3 ; 3/3 | 2/3 |

- Risk tasks selected from historical failures; this is not a representative full-suite success rate.
- Original 10-task full benchmark has not been rerun by this targeted execution.
- Runtime feedback and repeat/termination policies intentionally changed; task prompts, source files and scoring are frozen.
- Historical/current model aliases are mutable and runs are not contemporaneous; descriptive before/after only.
- Repeated trials share four tasks; do not treat 12 method trials as 12 independent bugs.
- tool_records includes reused/withheld observations; executed_tool_calls counts actual dispatches including verification, excluding denials/cache.
