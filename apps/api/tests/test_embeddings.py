"""Test della cache portabile degli embedding."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from ocio.embeddings import SMALL, EmbeddingError, generate_cache, load_cache


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def embed(self, texts: Sequence[str], model: str) -> Sequence[Sequence[float]]:
        self.calls.append((tuple(texts), model))
        return [[float(index)] * SMALL.dimension for index, _ in enumerate(texts)]


class FailingEmbeddingClient:
    def embed(self, texts: Sequence[str], model: str) -> Sequence[Sequence[float]]:
        raise RuntimeError("provider non disponibile")


class InvalidEmbeddingClient:
    def embed(self, texts: Sequence[str], model: str) -> Sequence[Sequence[float]]:
        return [[float("inf")]] * len(texts)


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def test_full_cache_hit_does_not_call_the_provider(tmp_path: Path) -> None:
    cache = tmp_path / "small.jsonl.gz"
    first_client = FakeEmbeddingClient()
    contents = {_digest("uno"): "uno", _digest("due"): "due"}
    created = generate_cache(
        contents, searchable_chunks=2, config=SMALL, path=cache, client=first_client
    )

    second_client = FakeEmbeddingClient()
    reused = generate_cache(
        contents, searchable_chunks=2, config=SMALL, path=cache, client=second_client
    )

    assert created.created_embeddings == 2
    assert reused.reused_embeddings == 2
    assert reused.created_embeddings == 0
    assert second_client.calls == []


def test_missing_embeddings_are_deduplicated_and_batched(tmp_path: Path) -> None:
    client = FakeEmbeddingClient()
    contents = {_digest(value): value for value in ("uno", "due", "tre")}

    report = generate_cache(
        contents,
        searchable_chunks=5,
        config=SMALL,
        path=tmp_path / "small.jsonl.gz",
        client=client,
        batch_size=2,
    )

    assert [len(call[0]) for call in client.calls] == [2, 1]
    assert report.searchable_chunks == 5
    assert report.unique_contents == 3
    assert report.created_embeddings == 3


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema_version": 2}, "versione schema"),
        ({"sha256": "non-un-hash"}, "SHA-256"),
        ({"model": "altro"}, "modello o dimensione"),
        ({"dimension": 12}, "modello o dimensione"),
        ({"vector": [0.0]}, "1536 dimensioni"),
        ({"vector": [float("nan")] * SMALL.dimension}, "non finiti"),
    ],
)
def test_invalid_cache_records_are_rejected(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    cache = tmp_path / "invalid.jsonl.gz"
    value: dict[str, object] = {
        "schema_version": 1,
        "sha256": "a" * 64,
        "model": SMALL.model,
        "dimension": SMALL.dimension,
        "vector": [0.0] * SMALL.dimension,
    }
    value.update(change)
    with gzip.open(cache, "wt", encoding="utf-8") as target:
        target.write(json.dumps(value) + "\n")

    with pytest.raises(EmbeddingError, match=message):
        load_cache(cache, SMALL)


def test_cache_bytes_are_deterministic(tmp_path: Path) -> None:
    contents = {_digest(value): value for value in ("tre", "uno", "due")}
    first = tmp_path / "first.jsonl.gz"
    second = tmp_path / "second.jsonl.gz"

    generate_cache(
        contents,
        searchable_chunks=3,
        config=SMALL,
        path=first,
        client=FakeEmbeddingClient(),
    )
    generate_cache(
        dict(reversed(tuple(contents.items()))),
        searchable_chunks=3,
        config=SMALL,
        path=second,
        client=FakeEmbeddingClient(),
    )

    assert first.read_bytes() == second.read_bytes()


def test_provider_error_leaves_the_previous_cache_unchanged(tmp_path: Path) -> None:
    cache = tmp_path / "small.jsonl.gz"
    initial = {_digest("uno"): "uno"}
    generate_cache(
        initial,
        searchable_chunks=1,
        config=SMALL,
        path=cache,
        client=FakeEmbeddingClient(),
    )
    previous = cache.read_bytes()

    with pytest.raises(RuntimeError, match="provider non disponibile"):
        generate_cache(
            {**initial, _digest("due"): "due"},
            searchable_chunks=2,
            config=SMALL,
            path=cache,
            client=FailingEmbeddingClient(),
        )

    assert cache.read_bytes() == previous


def test_invalid_provider_vectors_are_reported_as_embedding_errors(
    tmp_path: Path,
) -> None:
    content = "non valido"

    with pytest.raises(EmbeddingError, match="vettore"):
        generate_cache(
            {_digest(content): content},
            searchable_chunks=1,
            config=SMALL,
            path=tmp_path / "small.jsonl.gz",
            client=InvalidEmbeddingClient(),
        )
