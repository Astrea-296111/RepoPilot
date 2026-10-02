"""CLI entry points: run, inspect sessions, resume and serve HTTP."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import sys
import typer
from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.llm.openai_compatible import OpenAICompatibleLLM
from repopilot.session.store import SessionStore

app = typer.Typer(help="RepoPilot: inspect, edit and test a repository with an explicit agent loop")


@app.callback()
def configure_text_streams():
    """Keep Unicode summaries and stdio JSON usable when Windows stdout is redirected."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _llm(settings: Settings, fake_demo: bool):
    return FakeLLM(demo_responses()) if fake_demo else OpenAICompatibleLLM(settings)


def _approve(tool: str, args: dict) -> bool:
    typer.echo(f"请求授权 {tool}: {json.dumps(args, ensure_ascii=False)[:500]}")
    return typer.confirm("允许执行?", default=False)


@app.command()
def run(repo: Path, task: str, executor: str = typer.Option("docker", help="docker / local"),
        approval: str = typer.Option("ask", help="ask / auto / never"),
        runtime: str = typer.Option("custom", help="custom / langgraph"),
        tool_backend: str = typer.Option("python", help="python / mcp"),
        retrieval: str | None = typer.Option(None, help="legacy / hybrid"),
        reflection: bool = typer.Option(False, help="Enable a model reflection after each tool round"),
        memory: bool = typer.Option(False, help="Recall and store repository repair experiences"),
        fake_demo: bool = typer.Option(False, help="Key-free scripted run for examples/demo_repo only")):
    """Plan and execute one coding task; Docker and interactive approval are defaults."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if fake_demo and not (repo / "app" / "users.py").exists():
        raise typer.BadParameter("--fake-demo 仅适用于提供的 demo_repo")
    settings = Settings.load()
    settings.reflection_enabled = reflection or settings.reflection_enabled
    settings.memory_enabled = memory or settings.memory_enabled
    if retrieval is not None:
        settings = Settings.model_validate({**settings.model_dump(), "retrieval_mode": retrieval})
    try:
        agent = RepoPilot(repo, _llm(settings, fake_demo), settings, executor=executor,
                          approval=approval, approve=_approve, runtime=runtime, tool_backend=tool_backend)
    except (ValueError, OSError) as exc:
        typer.echo(f"配置错误: {exc}", err=True)
        raise typer.Exit(2) from exc
    result = agent.run(task)
    typer.echo(f"Session: {result.id}\nStatus: {result.status}\nTests: {result.test_status}\nSteps: {result.current_step}")
    typer.echo(result.summary or result.error)
    typer.echo("Git diff:\n" + result.final_diff)
    if result.status != "completed": raise typer.Exit(1)


@app.command()
def sessions(repo: Path = typer.Argument(Path("."))):
    """List persisted sessions, importing legacy JSON transcripts when present."""
    for state in SessionStore(repo).list():
        typer.echo(f"{state.id}  {state.status:<10} {state.current_step:>3} steps  {state.task[:80]}")


@app.command()
def show(session_id: str, repo: Path = typer.Option(Path("."))):
    """Print a saved session's complete JSON transcript."""
    typer.echo(SessionStore(repo).load(session_id).model_dump_json(indent=2))


@app.command()
def resume(session_id: str, repo: Path = typer.Option(Path(".")),
           executor: str = typer.Option("docker"), approval: str = typer.Option("ask"),
           runtime: str | None = typer.Option(None, help="Default: the saved session runtime")):
    """Continue a paused/failed session without replaying previous tools."""
    state = SessionStore(repo).load(session_id)
    settings = Settings.load().model_copy(update={"reflection_enabled": state.reflection_enabled,
                                                   "retrieval_mode": state.retrieval_mode,
                                                   "memory_enabled": state.memory_enabled})
    agent = RepoPilot(repo, OpenAICompatibleLLM(settings), settings,
                      executor=executor, approval=approval, approve=_approve, runtime=runtime or state.runtime,
                      tool_backend=state.tool_backend)
    result = agent.run(state.task, state)
    typer.echo(f"{result.id}: {result.status}; {result.summary or result.error}")
    if result.status != "completed": raise typer.Exit(1)


@app.command()
def mcp(repo: Path):
    """Start the optional, read-only MCP server over stdio; no API key is required."""
    from repopilot.mcp_server import create_server
    try:
        create_server(repo).run(transport="stdio")
    except (ValueError, OSError) as exc:
        typer.echo(f"MCP 配置错误: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command()
def retrieve(repo: Path, query: str, top_k: int = typer.Option(5, min=1, max=50)):
    """Show hybrid retrieval scores, locations and reasons without running the Agent."""
    from dataclasses import asdict
    from repopilot.context.embeddings import OpenAIEmbeddings
    from repopilot.context.hybrid import HybridIndex
    settings = Settings.load()
    try:
        embedder = (OpenAIEmbeddings(settings.embedding_base_url, settings.embedding_api_key, settings.embedding_model)
                    if settings.embedding_model else None)
        index = HybridIndex(repo, embedder=embedder)
        hits = index.search(query, top_k)
        typer.echo(json.dumps({"mode": index.mode, "cache_hit": index.cache_hit,
                               "hits": [asdict(hit) for hit in hits]}, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        typer.echo(f"检索错误: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Start the local REST API (no authentication; keep it private)."""
    import uvicorn
    uvicorn.run("repopilot.api.server:app", host=host, port=port)


if __name__ == "__main__": app()
