# RepoPilot Mini Benchmark v2

This directory contains deliberately buggy repositories used by the evaluation harness.

The agent receives only a fresh copy of one repository plus the task description. Hidden regression tests live under `eval/hidden_tests/` and are injected only after the agent finishes. The evaluator also rejects modifications under protected test paths.

The initial suite contains five small Python tasks spanning exception handling, boundary conditions, configuration precedence, path safety, and multi-file state management. It is a smoke benchmark, not a claim of general software-engineering performance.

A real-model miss is recorded as benchmark data rather than treated as CI infrastructure failure. The harness exits non-zero for runner/baseline errors; `--require-all` is used by the deterministic scripted sanity check to ensure the evaluator itself stays green.
