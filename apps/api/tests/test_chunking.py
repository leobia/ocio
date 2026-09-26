"""Chunk strategy contract tests."""

from __future__ import annotations

from ocio.chunking import (
    ChunkingConfig,
    SourcePartition,
    generate_fixed,
    generate_structural,
)


def partition(
    identifier: str,
    kind: str,
    content: str,
    *,
    id: int,
    parent_id: int | None = None,
    order: int = 1,
) -> SourcePartition:
    return SourcePartition(
        id=id,
        document_id=10,
        document_code="test",
        document_title="Documento di prova",
        acquisition_id=20,
        acquisition_sha256="a" * 64,
        parent_id=parent_id,
        identifier=identifier,
        kind=kind,
        rubric=None,
        order=order,
        content=content,
    )


def test_structural_merges_siblings_and_links_semantic_parent() -> None:
    partitions = [
        partition("art-1", "articolo", "", id=1),
        partition("art-1/comma-1", "comma", "", id=2, parent_id=1),
        partition("art-1/comma-1/a", "lettera", "Nomina il medico.", id=3, parent_id=2),
        partition(
            "art-1/comma-1/b",
            "lettera",
            "Designa gli addetti.",
            id=4,
            parent_id=2,
            order=2,
        ),
    ]

    chunks = generate_structural(partitions, ChunkingConfig(max_tokens=100))

    parent = next(chunk for chunk in chunks if chunk.role == "parent")
    child = next(chunk for chunk in chunks if chunk.role == "ricercabile")
    assert parent.identifier == "parent/art-1"
    assert parent.source_ids == (3, 4)
    assert child.source_ids == (3, 4)
    assert child.parent_identifier == parent.identifier
    assert "Nomina il medico" in child.content
    assert "Designa gli addetti" in child.content


def test_structural_splits_an_oversized_partition() -> None:
    partitions = [partition("art-1", "articolo", "obbligo " * 80, id=1)]

    chunks = generate_structural(partitions, ChunkingConfig(max_tokens=20))

    searchable = [chunk for chunk in chunks if chunk.role == "ricercabile"]
    assert len(searchable) > 1
    assert {chunk.source_ids for chunk in searchable} == {(1,)}


def test_token_windows_do_not_break_unicode_characters() -> None:
    partitions = [partition("art-1", "articolo", "😀 è utile " * 20, id=1)]

    chunks = generate_structural(partitions, ChunkingConfig(max_tokens=10))

    assert all("�" not in chunk.content for chunk in chunks)


def test_fixed_is_deterministic_and_defaults_to_no_overlap() -> None:
    partitions = [
        partition("art-1", "articolo", "primo " * 30, id=1),
        partition("art-2", "articolo", "secondo " * 30, id=2, order=2),
    ]
    config = ChunkingConfig(max_tokens=20)

    first = generate_fixed(partitions, config)
    second = generate_fixed(partitions, config)

    assert first == second
    assert config.overlap_tokens == 0
    assert len([chunk for chunk in first if chunk.role == "ricercabile"]) > 1
