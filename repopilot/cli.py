"""CLI entry points: run, inspect sessions, resume and serve HTTP."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import typer
from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.llm.openai_compatible import OpenAICompatibleLLM
from repopilot.session.store import SessionStore

app = typer.Typer(help="RepoPilot: inspect, edit and test a repository with an explicit agent loop")


def _llm(settings: Settings, fake_demo: bool):
    return FakeLLM(demo_responses()) if fake_demo else OpenAICompatibleLLM(settings)


def _approve(tool: str, args: dict) -> bool:
    typer.echo(f"请求授权 {tool}: {json.dumps(args, ensure_ascii=False)[:500]}")
    return typer.confirm("允许执行?", default=False)


@app.command()
def run(repo: Path, task: str, executor: str = typer.Option("docker", help="docker / local"),
        approval: str = typer.Option("ask", help="ask / auto / never"),
        fake_demo: bool = typer.Option(False, help="Key-free scripted run for examples/demo_repo only")):
    """Plan and execute one coding task; Docker and interactive approval are defaults."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if fake_demo and not (repo / "app" / "users.py").exists():
        raise typer.BadParameter("--fake-demo 仅适用于提供的 demo_repo")
    settings = Settings.load()
    try:
        agent = RepoPilot(repo, _llm(settings, fake_demo), settings, executor=executor, approval=approval, approve=_approve)
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
    """List JSON transcripts for a repository."""
    for state in SessionStore(repo).list():
        typer.echo(f"{state.id}  {state.status:<10} {state.current_step:>3} steps  {state.task[:80]}")


@app.command()
def show(session_id: str, repo: Path = typer.Option(Path("."))):
    """Print a saved session's complete JSON transcript."""
    typer.echo(SessionStore(repo).load(session_id).model_dump_json(indent=2))


@app.command()
def resume(session_id: str, repo: Path = typer.Option(Path(".")),
           executor: str = typer.Option("docker"), approval: str = typer.Option("ask")):
    """Continue a paused/failed session without replaying previous tools."""
    state = SessionStore(repo).load(session_id)
    agent = RepoPilot(repo, OpenAICompatibleLLM(Settings.load()), Settings.load(),
                      executor=executor, approval=approval, approve=_approve)
    result = agent.run(state.task, state)
    typer.echo(f"{result.id}: {result.status}; {result.summary or result.error}")
    if result.status != "completed": raise typer.Exit(1)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Start the local REST API (no authentication; keep it private)."""
    import uvicorn
    uvicorn.run("repopilot.api.server:app", host=host, port=port)


if __name__ == "__main__": app()

