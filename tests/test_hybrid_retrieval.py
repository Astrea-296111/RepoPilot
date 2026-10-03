"""Algorithm/protocol tests; fixture vectors do not measure semantic model quality."""
import json

import httpx
import pytest

pytest.importorskip("faiss")
pytest.importorskip("rank_bm25")

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.context.chunks import chunk_source
from repopilot.context.embeddings import OpenAIEmbeddings
from repopilot.context.hybrid import HybridIndex
from repopilot.llm.base import FakeLLM


class FixtureEmbeddings:
    """Explicit test double to verify FAISS wiring, never a production embedder."""
    cache_key = "test-fixture-v1"
    total_tokens = 0

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        return [[1.0, 0.0] if "enroll" in text or "账户开通" in text else [0.0, 1.0] for text in texts]


def test_bm25_ast_chinese_retrieval_with_reasons(runtime_repo):
    index = HybridIndex(runtime_repo)
    hits = index.search("修复用户注册重复邮箱")
    assert index.mode == "bm25+ast"
    assert hits[0].path == "app/users.py"
    assert hits[0].score > 0 and hits[0].scores["bm25"] is not None
    assert hits[0].start_line >= 1 and any("bm25" in r for r in hits[0].reason)
    assert index.search("", 0) == []


def test_faiss_roundtrip_cache_and_source_invalidation(tmp_path):
    (tmp_path / "accounts.py").write_text("def enroll(address):\n    return address\n")
    (tmp_path / "weather.py").write_text("def forecast():\n    return 'sunny'\n")
    embedder = FixtureEmbeddings()
    first = HybridIndex(tmp_path, embedder=embedder)
    hits = first.search("账户开通")
    assert first.mode == "bm25+vector+ast" and hits[0].path == "accounts.py"
    assert "vector" in hits[0].scores and hits[0].scores["vector"] == 1.0
    assert (first.directory / "faiss.index").is_file()
    assert (first.directory / "ast_index.json").is_file()
    assert (first.directory / "bm25_index.json").is_file()
    count = len(embedder.calls)
    second = HybridIndex(tmp_path, embedder=embedder)
    assert second.cache_hit and len(embedder.calls) == count
    assert second.search("账户开通")[0].path == hits[0].path
    (tmp_path / "accounts.py").write_text("def enroll(address):\n    return address.lower()\n")
    third = HybridIndex(tmp_path, embedder=embedder)
    assert not third.cache_hit and third.fingerprint != first.fingerprint
    embedder.cache_key = "test-fixture-v2"
    assert not HybridIndex(tmp_path, embedder=embedder).cache_hit


def test_empty_and_invalid_vectors(tmp_path):
    assert HybridIndex(tmp_path).search("anything") == []
    (tmp_path / "a.py").write_text("a=1")
    provider = FixtureEmbeddings()
    provider.embed = lambda texts: [[0.0, 0.0] for _ in texts]
    with pytest.raises(ValueError, match="zero vectors"):
        HybridIndex(tmp_path, embedder=provider)


def test_embedding_http_protocol_order_usage_and_rejection():
    def handler(request):
        assert request.url.path == "/v1/embeddings"
        body = json.loads(request.content)
        assert body["input"] == ["one", "two"] and body["model"] == "test-model"
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 1]},
                                                   {"index": 0, "embedding": [1, 0]}],
                                          "usage": {"total_tokens": 7}})
    model = OpenAIEmbeddings("https://example.invalid/v1", "test-key", "test-model",
                             transport=httpx.MockTransport(handler))
    assert model.embed(["one", "two"]) == [[1.0, 0.0], [0.0, 1.0]] and model.total_tokens == 7
    assert "test-key" not in model.cache_key
    bad = OpenAIEmbeddings("https://example.invalid", "test", "test",
                           transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": []})))
    with pytest.raises(ValueError, match="Embedding request failed"):
        bad.embed(["missing"])


def test_chunks_preserve_methods_locations_and_size():
    source = "import os\nclass User:\n    def register(self):\n        return 1\n"
    chunks = chunk_source("users.py", source)
    assert any("register" in c.symbols and "User" in c.symbols for c in chunks)
    assert all(c.start_line <= c.end_line for c in chunks)
    assert all(len(c.text) <= 2400 for c in chunk_source("long.txt", "x" * 6000))


def test_hybrid_is_used_in_agent_and_rebuilt_after_patch(runtime_repo):
    agent = RepoPilot(runtime_repo, FakeLLM(demo_responses()), Settings(retrieval_mode="hybrid"),
                      executor="local", approval="auto")
    state = agent.run("修复注册重复邮箱错误")
    assert state.status == "completed" and state.retrieval_backend == "bm25+ast"
    assert state.retrieval_results and state.retrieval_mode == "hybrid"
    generations = list((runtime_repo / ".repopilot/repo_index").glob("*/manifest.json"))
    assert len(generations) == 2  # initial broken source and patched source


def test_index_cache_cannot_escape_repository(runtime_repo, tmp_path):
    (runtime_repo / ".repopilot").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        HybridIndex(runtime_repo)


def test_shared_import_helper_survives_surface_keyword_matches(tmp_path):
    (tmp_path / "internal").mkdir()
    (tmp_path / "internal/core.py").write_text("def decide(value):\n    return value == 3\n")
    for name in ("retry_client", "background", "upload"):
        (tmp_path / f"{name}.py").write_text("from internal.core import decide\ndef retry_request(value):\n    return decide(value)\n")
    (tmp_path / "retry_notes.py").write_text("# retry request notes request retry\n")
    index = HybridIndex(tmp_path)
    hits = index.search("retry request", top_k=4)
    helper = next(hit for hit in hits if hit.path == "internal/core.py")
    assert "source importers=3" in helper.reason
    assert index.search("unmatchedxyz")[0].path == "internal/core.py"
