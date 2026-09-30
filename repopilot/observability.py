"""Opt-in OpenTelemetry spans with an explicit metadata allowlist and safe exporters."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import logging
import sys
import time
from urllib.parse import urlsplit

log = logging.getLogger(__name__)
ATTRIBUTES = {
    "repopilot.session.id", "repopilot.runtime", "repopilot.step", "repopilot.tool.name",
    "repopilot.ok", "repopilot.failure.category", "repopilot.duration_seconds",
    "repopilot.retrieved_file_count", "repopilot.changed_file_count", "repopilot.test.status",
    "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "gen_ai.usage.total_tokens",
    "repopilot.tool.cached", "repopilot.tool.executed",
}


class Span:
    """Expose only approved scalar metadata, never task/prompt/source/exception bodies."""
    def __init__(self, raw=None):
        self.raw = raw

    def set(self, attributes: dict) -> None:
        if self.raw is None:
            return
        for key, value in attributes.items():
            if key not in ATTRIBUTES or not isinstance(value, (str, bool, int, float)):
                raise ValueError("Telemetry accepts only allowlisted scalar metadata")
            self.raw.set_attribute(key, value[:120] if isinstance(value, str) else value)

    def fail(self, category: str) -> None:
        if self.raw is not None:
            from opentelemetry.trace import Status, StatusCode
            self.set({"repopilot.failure.category": category})
            self.raw.set_status(Status(StatusCode.ERROR, category))


class Tracing:
    """Use a private provider; do not modify a host application's global tracer provider."""
    def __init__(self, provider=None):
        self.provider = provider
        self.tracer = provider.get_tracer("repopilot", "0.1.0") if provider else None

    @classmethod
    def from_settings(cls, settings):
        """Disabled by default; SDK/exporter imports occur only after explicit opt-in."""
        if not settings.otel_enabled:
            return cls()
        if settings.otel_exporter not in {"console", "otlp"}:
            raise ValueError("REPOPILOT_OTEL_EXPORTER must be console or otlp")
        if settings.otel_exporter == "otlp":
            parsed = urlsplit(settings.otel_endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("OTLP requires an http(s) endpoint without embedded credentials")
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor, SpanExportResult
        except ImportError as exc:
            raise ValueError("Tracing requires: pip install -e '.[observability]' (from the RepoPilot checkout)") from exc
        if settings.otel_exporter == "console":
            exporter = ConsoleSpanExporter(out=sys.stderr)
        else:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            except ImportError as exc:
                raise ValueError("OTLP requires the observability extra") from exc
            exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, timeout=2)

        class SafeExporter:
            def export(self, spans):
                try:
                    return exporter.export(spans)
                except Exception:
                    log.warning("Trace export failed; agent execution continues")
                    return SpanExportResult.FAILURE

            def shutdown(self):
                try:
                    exporter.shutdown()
                except Exception:
                    log.warning("Trace exporter shutdown failed")

            def force_flush(self, timeout_millis=1000):
                try:
                    return exporter.force_flush(timeout_millis)
                except Exception:
                    return False

        provider = TracerProvider(resource=Resource.create({"service.name": "repopilot", "service.version": "0.1.0"}))
        processor = SimpleSpanProcessor if settings.otel_exporter == "console" else BatchSpanProcessor
        provider.add_span_processor(processor(SafeExporter()))
        return cls(provider)

    @contextmanager
    def span(self, name: str, attributes: dict | None = None):
        """Create a span without automatic recording of sensitive exception messages."""
        started = time.monotonic()
        context = (self.tracer.start_as_current_span(name, record_exception=False, set_status_on_exception=False)
                   if self.tracer else nullcontext(None))
        with context as raw:
            span = Span(raw)
            span.set(attributes or {})
            try:
                yield span
            except Exception as exc:
                span.fail(type(exc).__name__)
                raise
            finally:
                span.set({"repopilot.duration_seconds": time.monotonic() - started})

    def flush(self) -> bool:
        """Bound export waiting; telemetry transport failure does not fail a task."""
        if self.provider is None:
            return True
        try:
            return self.provider.force_flush(timeout_millis=1000)
        except Exception:
            log.warning("Trace flush failed; agent execution continues")
            return False
