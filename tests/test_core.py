import json
from pathlib import Path
import shutil
import subprocess
import time
import pytest
from fastapi.testclient import TestClient
from repopilot.agent.agent import RepoPilot, demo_responses, parse_action
from repopilot.agent.state import AgentState, Plan
from repopilot.api.server import app
from repopilot.config import Settings
from repopilot.context.manager import ContextManager
from repopilot.context.repo_map import build_repo_map, render_repo_map
from repopilot.context.retrieval import retrieve
from repopilot.llm.base import FakeLLM
from repopilot.session.store import SessionStore
from repopilot.tools.base import Workspace
from repopilot.tools.filesystem import ApplyPatch, ReadFile
from repopilot.tools.search import SearchCode
from repopilot.tools.shell import LocalExecutor, bounded_output


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/demo_repo", root)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "-qm", "baseline"], check=True)
    return root


def test_repo_map_extracts_symbols_and_skips_generated(repo):
    (repo / "node_modules").mkdir()
    (repo / "node_modules/hide.py").write_text("def secret(): pass")
    entries = build_repo_map(repo)
    mapped = render_repo_map(entries)
    assert "class UserService" in mapped and "def register(self, email: str, password: str) -> str" in mapped
    assert "def secret" not in mapped


def test_retrieval_finds_chinese_task(repo):
    found = retrieve(repo, build_repo_map(repo), "修复注册重复邮箱错误")
    assert found and found[0][0] == "app/users.py"


def test_path_boundary_and_symlink(repo, tmp_path):
    workspace = Workspace(repo)
    with pytest.raises(ValueError): workspace.resolve("../../secret")
    external = tmp_path / "outside.txt"
    external.write_text("SECRET")
    (repo / "link.txt").symlink_to(external)
    with pytest.raises(ValueError): ReadFile(workspace).execute({"path": "link.txt"})
    with pytest.raises(ValueError): workspace.resolve(".env", exists=False)


def test_read_search_patch(repo):
    workspace = Workspace(repo)
    assert "class UserService" in ReadFile(workspace).execute({"path": "app/users.py"}).output
    assert "app/users.py" in SearchCode(workspace).execute({"query": "UNIQUE"}).output
    patch = ApplyPatch(workspace).execute({"path": "app/users.py", "old_text": "raise ValueError('UNIQUE constraint failed: users.email')", "new_text": "raise DuplicateEmailError(email)"})
    assert patch.ok and patch.changed_file == "app/users.py"
    assert "DuplicateEmailError(email)" in (repo / "app/users.py").read_text()
    with pytest.raises(ValueError): ApplyPatch(workspace).execute({"path": "app/users.py", "old_text": "missing", "new_text": "x"})


def test_output_truncation_preserves_errors():
    output = "x" * 12000 + "\nFAILED test_duplicate_email\n" + "y" * 12000
    bounded = bounded_output(output, 1500)
    assert len(bounded) < 1600 and "FAILED test_duplicate_email" in bounded and bounded.endswith("y" * 50)


def test_context_budget_keeps_recent_observation(repo):
    state = AgentState(task="fix bug", repo_path=str(repo), plan=Plan(goal="fix"))
    state.tool_history = [{"tool": "run_command", "arguments": {"command": "pytest -q"}, "ok": False, "output": "FAILED duplicate email"}]
    context = ContextManager(2200).build(state, "map" * 2000, [("app/users.py", 7)])
    assert len(context) <= 2200 and "FAILED duplicate email" in context and "Task: fix bug" in context


def test_json_validation_rejects_extra_and_missing_fields():
    assert parse_action('{"type":"tool","tool":"git_diff","arguments":{},"reason":"check"}').tool == "git_diff"
    with pytest.raises(ValueError): parse_action('{"type":"tool","tool":"unknown","arguments":{},"reason":"x"}')
    with pytest.raises(ValueError): parse_action('{"type":"final","summary":"ok"}')


def test_session_storage(repo):
    store = SessionStore(repo)
    state = AgentState(task="bug", repo_path=str(repo))
    state.messages.append({"role": "tool", "content": "failed"})
    store.save(state)
    assert store.load(state.id).messages[0]["content"] == "failed"
    assert store.list()[0].id == state.id
    with pytest.raises(ValueError): store.load("../../etc/passwd")


def test_session_symlink_outside_workspace(repo, tmp_path):
    (repo / ".repopilot").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError): SessionStore(repo)


def test_local_command_timeout(repo):
    result = LocalExecutor(repo).run("python -c 'import time; time.sleep(2)'", 1)
    assert result.exit_code == 124 and "timed out" in result.output


def test_local_command_does_not_inherit_model_key(repo, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "should-not-be-visible")
    result = LocalExecutor(repo).run("python -c 'import os; print(os.getenv(\"LLM_API_KEY\", \"unset\"))'", 5)
    assert result.ok and result.output.strip() == "unset"


def test_fastapi_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_fastapi_blocks_repo_outside_root(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOPILOT_API_ROOT", str(tmp_path))
    response = TestClient(app).post("/api/tasks", json={"repo_path": "/", "task": "fix"})
    assert response.status_code == 400


def test_agent_loop_demo_end_to_end(repo):
    before = subprocess.run("python -m pytest -q", shell=True, cwd=repo, capture_output=True)
    assert before.returncode != 0
    agent = RepoPilot(repo, FakeLLM(demo_responses()), Settings(), executor="local", approval="auto")
    state = agent.run("修复重复邮箱注册失败的问题")
    after = subprocess.run("python -m pytest -q", shell=True, cwd=repo, capture_output=True)
    assert state.status == "completed" and state.test_status == "passed" and after.returncode == 0
    assert state.duration_seconds is not None and state.duration_seconds > 0
    assert state.changed_files == ["app/users.py"] and "DuplicateEmailError" in state.final_diff
    assert state.tool_history[1]["ok"] is False and state.tool_history[3]["ok"] is True


def test_agent_loop_detection(repo):
    plan = demo_responses()[0]
    repeat = json.dumps({"type": "tool", "tool": "read_file", "arguments": {"path": "app/users.py"}, "reason": "again"})
    state = RepoPilot(repo, FakeLLM([plan, repeat, repeat, repeat]), Settings(), executor="local", approval="auto").run("fix")
    assert state.status == "failed" and state.error == "loop_detection" and state.current_step == 3


def test_approval_never_blocks_patch(repo):
    plan = demo_responses()[0]
    patch = demo_responses()[3]
    state = RepoPilot(repo, FakeLLM([plan, patch, patch, patch]), Settings(), executor="local", approval="never").run("fix")
    assert state.status == "failed" and "Approval denied" in state.tool_history[0]["output"]
    assert "raise ValueError" in (repo / "app/users.py").read_text()


def test_invalid_json_repair_once(repo):
    responses = [demo_responses()[0], "bad JSON", "still bad JSON"]
    state = RepoPilot(repo, FakeLLM(responses), Settings(), executor="local", approval="auto").run("fix")
    assert state.status == "failed" and "无效 JSON" in state.error


def test_final_claim_cannot_override_failing_test(repo):
    plan = demo_responses()[0]
    final = demo_responses()[-1]
    state = RepoPilot(repo, FakeLLM([plan, final, final]), Settings(max_steps=2), executor="local", approval="auto").run("fix")
    assert state.status == "failed" and state.test_status == "failed"
    assert len(state.tool_history) == 2 and all(not entry["ok"] for entry in state.tool_history)


def test_success_requires_git_diff(repo):
    shutil.rmtree(repo / ".git")
    state = RepoPilot(repo, FakeLLM(demo_responses()), Settings(), executor="local", approval="auto").run("fix")
    assert state.status == "failed" and state.error == "git_diff_failed"
    assert state.test_status == "passed"


def test_resume_continues_without_replaying_tools(repo):
    responses = demo_responses()
    first = RepoPilot(repo, FakeLLM(responses[:2]), Settings(), executor="local", approval="auto").run("fix")
    assert first.status == "failed" and first.current_step == 1
    second = RepoPilot(repo, FakeLLM(responses[2:]), Settings(), executor="local", approval="auto").run(first.task, first)
    assert second.status == "completed" and second.current_step == 6
    assert [item["tool"] for item in second.tool_history].count("read_file") == 1
    assert SessionStore(repo).load(first.id).status == "completed"
