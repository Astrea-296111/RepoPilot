"""BM25 + FAISS recall, reciprocal-rank fusion and explainable AST reranking."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from .chunks import CodeChunk, chunk_source, tokenize
from .embeddings import EmbeddingProvider
from .repo_map import FileEntry, build_repo_map
from .retrieval import _local_imports

log = logging.getLogger(__name__)


@dataclass
class RetrievalHit:
    path: str
    score: float
    reason: list[str]
    start_line: int
    end_line: int
    scores: dict[str, float]


class HybridIndex:
    """Content-addressed immutable cache generations; no pickle deserialization.

    A changed source file or embedding provider creates a new generation. Builds
    publish by atomic directory rename so readers never consume half an index.
    """
    VERSION = 1

    def __init__(self, root: Path, entries: list[FileEntry] | None = None,
                 embedder: EmbeddingProvider | None = None) -> None:
        try:
            import faiss
            import numpy as np
            from rank_bm25 import BM25Okapi
        except ImportError as exc:
            raise ValueError("Hybrid retrieval requires: pip install -e '.[rag]'") from exc
        self.faiss, self.np, self.bm25_type = faiss, np, BM25Okapi
        self.root, self.embedder = root.resolve(), embedder
        self.entries = entries if entries is not None else build_repo_map(self.root)
        self.chunks: list[CodeChunk] = []
        self.vector_index: Any = None
        self.cache_hit = False
        sources: dict[str, str] = {}
        for entry in self.entries:
            target = (self.root / entry.path).resolve()
            if not target.is_relative_to(self.root):
                raise ValueError("Index source escapes repository")
            sources[entry.path] = target.read_text(encoding="utf-8", errors="replace")
        fingerprint = {"version": self.VERSION, "provider": embedder.cache_key if embedder else "bm25-ast",
                       "sources": {p: hashlib.sha256(s.encode()).hexdigest() for p, s in sources.items()}}
        self.fingerprint = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        cache = self.root / ".repopilot" / "repo_index"
        if not cache.resolve().is_relative_to(self.root):
            raise ValueError("Index cache escapes repository")
        cache.mkdir(parents=True, exist_ok=True)
        self.directory = cache / self.fingerprint
        if self.directory.is_symlink():
            raise ValueError("Index generation must not be a symlink")
        if self.directory.exists():
            self._load()
            self.cache_hit = True
        else:
            for path, source in sources.items():
                self.chunks.extend(chunk_source(path, source))
            if len(self.chunks) > 50000:
                raise ValueError("Index exceeds 50000 chunks; narrow the repository")
            if embedder and self.chunks:
                vectors = self._matrix(embedder.embed([self._document(c) for c in self.chunks]), len(self.chunks))
                self.vector_index = faiss.IndexFlatIP(vectors.shape[1])
                self.vector_index.add(vectors)
            self._save(fingerprint)
        corpus = [tokenize(self._document(chunk)) or ["__empty__"] for chunk in self.chunks]
        self.corpus = corpus
        self.bm25 = BM25Okapi(corpus) if corpus else None
        self.mode = "bm25+vector+ast" if self.vector_index is not None else "bm25+ast"
        log.info("retrieval index mode=%s chunks=%s cache_hit=%s", self.mode, len(self.chunks), self.cache_hit)

    @staticmethod
    def _document(chunk: CodeChunk) -> str:
        return f"{chunk.path}\n{' '.join(chunk.symbols)}\n{chunk.text}"

    def _matrix(self, vectors: list[list[float]], count: int) -> Any:
        matrix = self.np.asarray(vectors, dtype="float32")
        if matrix.ndim != 2 or matrix.shape[0] != count or matrix.shape[1] < 1:
            raise ValueError("Embedding matrix shape does not match chunks")
        norms = self.np.linalg.norm(matrix, axis=1)
        if not self.np.isfinite(matrix).all() or (norms == 0).any():
            raise ValueError("Embedding matrix contains non-finite or zero vectors")
        self.faiss.normalize_L2(matrix)
        return matrix

    def _save(self, manifest: dict) -> None:
        temporary = Path(tempfile.mkdtemp(prefix=".build-", dir=self.directory.parent))
        try:
            (temporary / "ast_index.json").write_text(json.dumps([asdict(e) for e in self.entries]), encoding="utf-8")
            (temporary / "chunks.json").write_text(json.dumps([asdict(c) for c in self.chunks]), encoding="utf-8")
            # Portable corpus, reconstructed by rank_bm25; no executable pickle cache.
            (temporary / "bm25_index.json").write_text(json.dumps([tokenize(self._document(c)) for c in self.chunks]), encoding="utf-8")
            if self.vector_index is not None:
                self.faiss.write_index(self.vector_index, str(temporary / "faiss.index"))
            (temporary / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            try:
                os.rename(temporary, self.directory)
            except OSError:
                if not self.directory.is_dir():
                    raise
                log.info("concurrent index generation already published")
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def _load(self) -> None:
        try:
            for file in self.directory.iterdir():
                if file.is_symlink():
                    raise ValueError("Index artifacts must not be symlinks")
            self.chunks = [CodeChunk(**row) for row in json.loads((self.directory / "chunks.json").read_text())]
            if any(not (self.root / c.path).resolve().is_relative_to(self.root) for c in self.chunks):
                raise ValueError("Cached source escapes repository")
            if self.embedder and self.chunks:
                self.vector_index = self.faiss.read_index(str(self.directory / "faiss.index"))
                if self.vector_index.ntotal != len(self.chunks):
                    raise ValueError("Vector/chunk count mismatch")
        except (ValueError, OSError, RuntimeError, TypeError) as exc:
            raise ValueError("Invalid index cache; remove .repopilot/repo_index and rebuild") from exc

    def search(self, query: str, top_k: int = 5) -> list[RetrievalHit]:
        if top_k <= 0 or not query.strip() or not self.chunks:
            return []
        terms = tokenize(query)
        term_set = set(terms)
        raw = self.bm25.get_scores(terms)
        limit = min(len(self.chunks), max(top_k * 4, 20))
        lexical = sorted((i for i, tokens in enumerate(self.corpus) if term_set.intersection(tokens)),
                         key=lambda i: (-raw[i], self.chunks[i].path, self.chunks[i].start_line))[:limit]
        fused: dict[int, float] = {}
        reasons: dict[int, list[str]] = {}
        scores: dict[int, dict[str, float]] = {}

        def add(index: int, rank: int, channel: str, value: float) -> None:
            fused[index] = fused.get(index, 0) + 1 / (60 + rank)
            reasons.setdefault(index, []).append(f"{channel} rank={rank}")
            scores.setdefault(index, {})[channel] = float(value)

        for rank, i in enumerate(lexical, 1):
            add(i, rank, "bm25", raw[i])
        if self.vector_index is not None and self.embedder:
            matrix = self._matrix(self.embedder.embed([query]), 1)
            if matrix.shape[1] != self.vector_index.d:
                raise ValueError("Query embedding dimension differs from index; rebuild with the same model")
            distances, indices = self.vector_index.search(matrix, limit)
            for rank, (value, i) in enumerate(zip(distances[0], indices[0]), 1):
                if i >= 0 and value > 0:
                    add(int(i), rank, "vector", value)
        files: dict[str, RetrievalHit] = {}
        for i, score in fused.items():
            chunk = self.chunks[i]
            overlap = term_set.intersection(tokenize(" ".join(chunk.symbols)))
            boost = min(len(overlap), 3) * 0.003
            why = list(reasons[i])
            if overlap:
                why.append("AST symbols: " + ", ".join(sorted(overlap)))
            hit = RetrievalHit(chunk.path, score + boost, why, chunk.start_line, chunk.end_line,
                               {**scores[i], "rrf": score, "ast": boost})
            if chunk.path not in files or hit.score > files[chunk.path].score:
                files[chunk.path] = hit
        anchors = sorted(files.values(), key=lambda h: (-h.score, h.path))[:2]
        edges = _local_imports(self.entries)
        for anchor in anchors:
            for path in edges.get(anchor.path, set()):
                if path not in files:
                    chunk = next((c for c in self.chunks if c.path == path), None)
                    if chunk:
                        files[path] = RetrievalHit(path, 0.012, [], chunk.start_line, chunk.end_line, {"ast": 0.0})
                if path in files:
                    files[path].score += 0.005
                    files[path].scores["ast"] += 0.005
                    files[path].reason.append("AST import from " + anchor.path)
        ranked = sorted(files.values(), key=lambda hit: (-hit.score, hit.path))[:top_k]
        for hit in ranked:
            hit.score = round(hit.score, 6)
            hit.scores = {key: round(value, 6) for key, value in hit.scores.items()}
        return ranked
