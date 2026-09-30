"""Official MCP client speaks the protocol to both a real subprocess and in-memory server."""
import asyncio
import subprocess
import sys

import pytest

pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters
from repopilot.mcp_server import create_server


def text(result):
    return "\n".join(item.text for item in result.content if hasattr(item, "text"))


def test_official_stdio_client_lifecycle_and_read_only_tools(runtime_repo, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("PRIVATE_SENTINEL")
    (runtime_repo / "escape.txt").symlink_to(outside)
    source = runtime_repo / "app/users.py"
    source.write_text(source.read_text() + "\n# local diff marker\n")

    async def exercise():
        params = StdioServerParameters(command=sys.executable,
                                        args=["-m", "repopilot.cli", "mcp", str(runtime_repo)])
        async with Client(params, read_timeout_seconds=10) as client:
            listing = await client.list_tools()
            assert {t.name for t in listing.tools} == {"repo_map", "search_code", "read_file", "git_diff"}
            assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in listing.tools)
            read = await client.call_tool("read_file", {"path": "app/users.py"})
            search = await client.call_tool("search_code", {"query": "UNIQUE"})
            mapped = await client.call_tool("repo_map")
            diff = await client.call_tool("git_diff")
            assert not any(r.is_error for r in (read, search, mapped, diff))
            assert "class UserService" in text(read)
            assert "app/users.py" in text(search) and "class UserService" in text(mapped)
            assert "local diff marker" in text(diff)
            for path in ("../secret.txt", "escape.txt", ".env", ".git/config", ".repopilot/sessions/x.json"):
                rejected = await client.call_tool("read_file", {"path": path})
                assert rejected.is_error and "PRIVATE_SENTINEL" not in text(rejected)
            assert "PRIVATE_SENTINEL" not in text(await client.call_tool("search_code", {"query": "PRIVATE"}))
            assert (await client.call_tool("apply_patch", {})).is_error
        # Leaving the client context must close its server subprocess cleanly.

    asyncio.run(asyncio.wait_for(exercise(), timeout=40))
    assert not (runtime_repo / ".repopilot").exists()


def test_mcp_limits_and_non_git_error(tmp_path):
    (tmp_path / "large.py").write_text("x" * 512001)
    (tmp_path / "long.txt").write_text("public " * 4000)

    async def exercise():
        async with Client(create_server(tmp_path), read_timeout_seconds=5) as client:
            assert (await client.call_tool("read_file", {"path": "large.py"})).is_error
            assert (await client.call_tool("read_file", {"path": "long.txt", "end_line": 301})).is_error
            assert (await client.call_tool("search_code", {"query": "x", "path": "large.py"})).is_error
            bounded = await client.call_tool("read_file", {"path": "long.txt"})
            assert not bounded.is_error and len(text(bounded)) <= 12000
            nongit = await client.call_tool("git_diff")
            assert nongit.is_error and "git" in text(nongit).lower()
            assert (await client.call_tool("repo_map", {"path": "../"})).is_error
            assert (await client.call_tool("repo_map", {"max_files": 0})).is_error

    asyncio.run(asyncio.wait_for(exercise(), timeout=20))


def test_invalid_mcp_repository_exits_with_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_server(tmp_path / "missing")
    result = subprocess.run([sys.executable, "-m", "repopilot.cli", "mcp", str(tmp_path / "missing")],
                            capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 2 and "MCP" in result.stderr


def test_mcp_git_diff_excludes_private_files_and_never_runs_external_diff(runtime_repo, monkeypatch):
    private = runtime_repo / ".env"
    private.write_text("KEY=baseline")
    subprocess.run(["git", "-C", str(runtime_repo), "add", "-f", ".env"], check=True, timeout=10)
    subprocess.run(["git", "-C", str(runtime_repo), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "-qm", "private fixture"], check=True, timeout=10)
    private.write_text("KEY=PRIVATE_DIFF_SENTINEL")
    source = runtime_repo / "app/users.py"
    source.write_text(source.read_text() + "\n# public change\n")
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", "a-nonexistent-program-that-must-never-run")

    async def exercise():
        async with Client(create_server(runtime_repo), read_timeout_seconds=5) as client:
            result = await client.call_tool("git_diff")
            assert not result.is_error
            assert "public change" in text(result) and "PRIVATE_DIFF_SENTINEL" not in text(result)

    asyncio.run(asyncio.wait_for(exercise(), timeout=20))
