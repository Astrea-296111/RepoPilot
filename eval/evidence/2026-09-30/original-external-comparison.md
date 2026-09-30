# RepoPilot 外部历史 Bug 评测

模型：qwen3.8-max；10 个任务 × 3 次 × 2 种方法，共 60 次。

| 方法 | 隐藏评分通过 | Token 中位数 | 同口径端到端耗时中位数 |
|---|---:|---:|---:|
| agent | 25/30 | 34337.5 | 123.904s |
| oneshot | 28/30 | 5003.0 | 36.492s |

| 任务 | Agent | One-shot |
|---|---:|---:|
| boltons_backoff | 3/3 | 3/3 |
| boltons_research | 0/3 | 3/3 |
| boltons_split | 3/3 | 3/3 |
| boltons_xfrange | 3/3 | 3/3 |
| more_nth_combination | 3/3 | 3/3 |
| more_nth_permutation | 3/3 | 3/3 |
| more_numeric_slice | 3/3 | 3/3 |
| more_predicate_sentinel | 3/3 | 3/3 |
| slugify_hex | 2/3 | 3/3 |
| slugify_truncation | 2/3 | 1/3 |

成功率差：-10.0 个百分点；按任务重采样的 95% 区间：[-33.33333333333333, 6.666666666666667]。

注意：只有 10 个独立任务，重复次数不能当成 30 个独立 Bug。范围为上游模块快照及固定回归用例，不能声称完整仓库集成修复能力或行业 Benchmark 得分。
