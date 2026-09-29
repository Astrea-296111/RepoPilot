# RepoPilot Mini Benchmark v3

This directory contains deliberately buggy Python repositories used by the evaluation harness.

The agent or one-shot baseline receives a fresh repository copy and the task description. Hidden regression tests live under `eval/hidden_tests/` and are injected only after the repair attempt finishes.

Public `tests/` are grader-owned. A model may edit them during its repair process, but those edits are recorded and then discarded before grading. The evaluator restores the original public tests, injects the hidden regression test, and grades the resulting source patch against both. This prevents weakened tests from creating false success without unfairly penalizing an agent that adds legitimate tests while debugging.

The v3 suite contains 20 tasks across exception handling, boundary conditions, configuration, path safety, state management, normalization, parsing, authorization, recursive merge logic, and other small Python maintenance bugs. It is still a small benchmark and not a claim of general software-engineering performance.
