"""Real SDK exporter assertions for privacy, accounting, nesting and error status."""
import json

import pytest

pytest.importorskip("opentelemetry.sdk")
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.observability import ATTRIBUTES, Tracing


@pytest.mark.parametrize("runtime", ["custom", "langgraph"])
def test_exported_spans_tokens_duration_nesting_and_privacy(runtime_repo, runtime):
    if runtime == "langgraph":
        pytest.importorskip("langgraph")
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    class MeteredFake(FakeLLM):
        def chat(self, system, user):
            result = super().chat(system, user)
            result.prompt_tokens, result.completion_tokens = 7, 3
            return result

    sentinel = "PRIVATE_TASK_SOURCE_KEY_SENTINEL"
    source = runtime_repo / "app/users.py"
    source.write_text(source.read_text() + "\n# " + sentinel + "\n")
    state = RepoPilot(runtime_repo, MeteredFake(demo_responses()), Settings(llm_api_key=sentinel),
                      runtime=runtime, executor="local", approval="auto", tracing=Tracing(provider)).run(sentinel)
    assert state.status == "completed"
    spans = exporter.get_finished_spans()
    names = {s.name for s in spans}
    assert {"repopilot.task", "retrieval", "planning", "llm.call", "agent.turn", "tool.read_file",
            "tool.apply_patch", "tool.run_command", "verification"}.issubset(names)
    task = next(s for s in spans if s.name == "repopilot.task")
    assert task.attributes["repopilot.runtime"] == runtime
    assert task.attributes["repopilot.ok"]
    llm = [s for s in spans if s.name == "llm.call"]
    assert sum(s.attributes["gen_ai.usage.total_tokens"] for s in llm) == state.token_usage["total_tokens"] == 70
    assert all(s.attributes["gen_ai.usage.input_tokens"] == 7 and s.attributes["gen_ai.usage.output_tokens"] == 3 for s in llm)
    assert all(s.attributes["repopilot.duration_seconds"] >= 0 and s.end_time >= s.start_time for s in spans)
    assert all(s.context.trace_id == task.context.trace_id for s in spans)
    verification = next(s for s in spans if s.name == "verification")
    assert any(s.name == "tool.run_command" and s.parent.span_id == verification.context.span_id for s in spans)
    assert any(s.name == "tool.run_command" and s.status.status_code == StatusCode.ERROR for s in spans)
    assert all(set(s.attributes).issubset(ATTRIBUTES) and not s.events for s in spans)
    serialized = json.dumps([dict(s.attributes) for s in spans])
    assert sentinel not in serialized and "old_text" not in serialized and "prompt" not in serialized
    provider.shutdown()


def test_llm_failure_has_error_span_without_exception_body(runtime_repo):
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    class Failure:
        def chat(self, system, user):
            raise RuntimeError("PRIVATE_EXCEPTION_BODY")

    result = RepoPilot(runtime_repo, Failure(), Settings(), executor="local", approval="auto",
                       tracing=Tracing(provider)).run("fix")
    assert result.status == "failed"
    spans = exporter.get_finished_spans()
    failed = [s for s in spans if s.name in {"llm.call", "planning", "repopilot.task"}]
    assert len(failed) == 3 and all(s.status.status_code == StatusCode.ERROR for s in failed)
    assert all("PRIVATE_EXCEPTION_BODY" not in s.to_json() for s in spans)
    provider.shutdown()


@pytest.mark.parametrize("settings,match", [
    (Settings(otel_enabled=True, otel_exporter="unknown"), "EXPORTER"),
    (Settings(otel_enabled=True, otel_exporter="otlp"), "endpoint"),
    (Settings(otel_enabled=True, otel_exporter="otlp", otel_endpoint="http://user:password@host"), "credentials"),
])
def test_bad_exporter_configuration_is_explicit(settings, match):
    with pytest.raises(ValueError, match=match):
        Tracing.from_settings(settings)


def test_exporter_exception_does_not_change_agent_result(runtime_repo, monkeypatch):
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter
    calls = []
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    def fail(self, spans):
        calls.append(len(spans))
        raise RuntimeError("unreachable")
    monkeypatch.setattr(ConsoleSpanExporter, "export", fail)
    pilot = RepoPilot(runtime_repo, FakeLLM(demo_responses()), Settings(otel_enabled=True),
                      executor="local", approval="auto")
    assert pilot.run("fix").status == "completed"
    assert calls
    pilot.tracing.provider.shutdown()


def test_metadata_allowlist_rejects_source_bodies():
    provider = TracerProvider(sampler=ALWAYS_ON)
    with pytest.raises(ValueError, match="allowlisted"):
        with Tracing(provider).span("test", {"prompt": "private code"}):
            pass
    provider.shutdown()


def test_otlp_http_export_to_local_collector(monkeypatch, tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    received = []
    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()
        def log_message(self, *args):
            pass

    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Exercise documented env loading, including a blank traces endpoint from
    # .env.example and the generic endpoint fallback, through the real exporter.
    monkeypatch.setenv("REPOPILOT_OTEL_ENABLED", "1")
    monkeypatch.setenv("REPOPILOT_OTEL_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{server.server_port}/v1/traces")
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    tracing = Tracing.from_settings(Settings.load(env_file))
    try:
        with tracing.span("repopilot.task", {"repopilot.runtime": "custom"}):
            pass
        assert tracing.flush()
        assert received
        message = ExportTraceServiceRequest.FromString(received[0])
        assert message.resource_spans[0].scope_spans[0].spans[0].name == "repopilot.task"
    finally:
        tracing.provider.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
