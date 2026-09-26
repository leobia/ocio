"""Generate deterministic chunk sets from current document partitions."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

import tiktoken
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from ocio.bm25 import ensure_bm25_index
from ocio.database import database_url

Strategy = Literal["fixed", "structural"]
Role = Literal["ricercabile", "parent"]
STRATEGY_REVISION = 2
SEMANTIC_TYPES = frozenset({"articolo", "domanda", "punto", "allegato"})


class ChunkingError(Exception):
    """Chunks cannot be generated from the current corpus."""


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    """Versioned knobs shared by both initial strategies."""

    max_tokens: int = 512
    overlap_tokens: int = 0
    encoding: str = "cl100k_base"

    def validate(self) -> None:
        if self.max_tokens < 1:
            raise ChunkingError("max_tokens deve essere positivo.")
        if self.overlap_tokens < 0:
            raise ChunkingError("overlap_tokens non può essere negativo.")
        if self.overlap_tokens >= self.max_tokens:
            raise ChunkingError("overlap_tokens deve essere minore di max_tokens.")
        try:
            tiktoken.get_encoding(self.encoding)
        except ValueError as error:
            raise ChunkingError(f"Tokenizer sconosciuto: {self.encoding}.") from error


@dataclass(frozen=True, slots=True)
class SourcePartition:
    id: int
    document_id: int
    document_code: str
    document_title: str
    acquisition_id: int
    acquisition_sha256: str
    parent_id: int | None
    identifier: str
    kind: str
    rubric: str | None
    order: int
    content: str


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    identifier: str
    document_id: int
    role: Role
    order: int
    content: str
    source_ids: tuple[int, ...]
    parent_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkingReport:
    set_id: int
    strategy: Strategy
    chunks: int
    parents: int
    reused: bool


class _Corpus:
    def __init__(self, partitions: Sequence[SourcePartition]) -> None:
        self.by_id = {partition.id: partition for partition in partitions}
        self.children: defaultdict[int | None, list[SourcePartition]] = defaultdict(
            list
        )
        self.documents: defaultdict[int, list[SourcePartition]] = defaultdict(list)
        for partition in partitions:
            self.children[partition.parent_id].append(partition)
            self.documents[partition.document_id].append(partition)
        for siblings in self.children.values():
            siblings.sort(key=lambda item: (item.order, item.identifier))

    def ordered(self, document_id: int) -> list[SourcePartition]:
        result: list[SourcePartition] = []

        def visit(partition: SourcePartition) -> None:
            result.append(partition)
            for child in self.children[partition.id]:
                visit(child)

        roots = [
            partition
            for partition in self.documents[document_id]
            if partition.parent_id is None
        ]
        for root in sorted(roots, key=lambda item: (item.order, item.identifier)):
            visit(root)
        return result

    def descendants_with_content(self, partition_id: int) -> list[SourcePartition]:
        result: list[SourcePartition] = []

        def visit(current: SourcePartition) -> None:
            if current.content.strip():
                result.append(current)
            for child in self.children[current.id]:
                visit(child)

        visit(self.by_id[partition_id])
        return result

    def path(self, partition: SourcePartition) -> list[SourcePartition]:
        path = [partition]
        while path[-1].parent_id is not None:
            path.append(self.by_id[path[-1].parent_id])
        path.reverse()
        return path

    def semantic_parent(
        self, sources: Sequence[SourcePartition]
    ) -> SourcePartition | None:
        if not sources:
            return None
        ancestor_paths: list[list[SourcePartition]] = []
        for source in sources:
            path = self.path(source)
            if path and path[-1].id == source.id:
                path = path[:-1]
            ancestor_paths.append(path)
        common_ids = set(item.id for item in ancestor_paths[0])
        for path in ancestor_paths[1:]:
            common_ids.intersection_update(item.id for item in path)
        for candidate in reversed(ancestor_paths[0]):
            if candidate.id in common_ids and candidate.kind in SEMANTIC_TYPES:
                return candidate
        return None


def _partition_text(corpus: _Corpus, partition: SourcePartition) -> str:
    path = corpus.path(partition)
    labels = [" ".join(filter(None, (item.identifier, item.rubric))) for item in path]
    context = " > ".join(labels)
    return f"Percorso: {context}\n{partition.content.strip()}".strip()


def _chunk_text(corpus: _Corpus, sources: Sequence[SourcePartition], body: str) -> str:
    first = sources[0]
    return f"Documento: {first.document_title}\n{body.strip()}".strip()


def _split_tokens(value: str, *, size: int, overlap: int, encoding: str) -> list[str]:
    tokenizer = tiktoken.get_encoding(encoding)
    tokens = tokenizer.encode(value)
    if not tokens:
        return []
    decoded, offsets = tokenizer.decode_with_offsets(tokens)
    pieces: list[str] = []
    for start, end in _token_ranges(offsets, size=size, overlap=overlap):
        char_start = offsets[start]
        char_end = offsets[end] if end < len(tokens) else len(decoded)
        pieces.append(decoded[char_start:char_end])
    return pieces


def _token_ranges(
    offsets: Sequence[int], *, size: int, overlap: int
) -> Iterable[tuple[int, int]]:
    """Yield windows without cutting a multi-token UTF-8 character."""
    start = 0
    while start < len(offsets):
        end = min(start + size, len(offsets))
        while end < len(offsets) and offsets[end] == offsets[end - 1]:
            end += 1
        yield start, end
        if end == len(offsets):
            return
        next_start = max(end - overlap, start + 1)
        while (
            next_start < len(offsets)
            and next_start > 0
            and offsets[next_start] == offsets[next_start - 1]
        ):
            next_start += 1
        start = next_start


def _unique_in_order(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(values))


def _parent_draft(corpus: _Corpus, parent: SourcePartition) -> ChunkDraft:
    sources = corpus.descendants_with_content(parent.id)
    body = "\n\n".join(_partition_text(corpus, source) for source in sources)
    return ChunkDraft(
        identifier=f"parent/{parent.identifier}",
        document_id=parent.document_id,
        role="parent",
        order=0,
        content=_chunk_text(corpus, sources, body),
        source_ids=tuple(source.id for source in sources),
    )


def _attach_parents(corpus: _Corpus, drafts: list[ChunkDraft]) -> list[ChunkDraft]:
    parents: dict[tuple[int, str], ChunkDraft] = {}
    searchable: list[ChunkDraft] = []
    for draft in drafts:
        sources = [corpus.by_id[source_id] for source_id in draft.source_ids]
        parent = corpus.semantic_parent(sources)
        parent_identifier = None
        if parent is not None:
            parent_draft = _parent_draft(corpus, parent)
            parents[(parent.document_id, parent_draft.identifier)] = parent_draft
            parent_identifier = parent_draft.identifier
        searchable.append(
            ChunkDraft(
                identifier=draft.identifier,
                document_id=draft.document_id,
                role=draft.role,
                order=draft.order,
                content=draft.content,
                source_ids=draft.source_ids,
                parent_identifier=parent_identifier,
            )
        )
    return [*parents.values(), *searchable]


def generate_fixed(
    partitions: Sequence[SourcePartition], config: ChunkingConfig
) -> list[ChunkDraft]:
    """Generate fixed token windows over each document's ordered content."""
    config.validate()
    corpus = _Corpus(partitions)
    tokenizer = tiktoken.get_encoding(config.encoding)
    drafts: list[ChunkDraft] = []
    for document_id in sorted(corpus.documents):
        sources = [
            partition
            for partition in corpus.ordered(document_id)
            if partition.content.strip()
        ]
        token_stream: list[int] = []
        token_sources: list[int] = []
        for source in sources:
            source_tokens = tokenizer.encode(_partition_text(corpus, source) + "\n\n")
            token_stream.extend(source_tokens)
            token_sources.extend([source.id] * len(source_tokens))
        decoded, offsets = tokenizer.decode_with_offsets(token_stream)
        order = 0
        for start, end in _token_ranges(
            offsets,
            size=config.max_tokens,
            overlap=config.overlap_tokens,
        ):
            order += 1
            source_ids = _unique_in_order(token_sources[start:end])
            window_sources = [corpus.by_id[source_id] for source_id in source_ids]
            char_start = offsets[start]
            char_end = offsets[end] if end < len(token_stream) else len(decoded)
            drafts.append(
                ChunkDraft(
                    identifier=f"fixed/{order:06d}",
                    document_id=document_id,
                    role="ricercabile",
                    order=order,
                    content=_chunk_text(
                        corpus, window_sources, decoded[char_start:char_end].strip()
                    ),
                    source_ids=source_ids,
                )
            )
    return _attach_parents(corpus, drafts)


def generate_structural(
    partitions: Sequence[SourcePartition], config: ChunkingConfig
) -> list[ChunkDraft]:
    """Merge short sibling partitions and split oversized partitions."""
    config.validate()
    corpus = _Corpus(partitions)
    tokenizer = tiktoken.get_encoding(config.encoding)
    drafts: list[ChunkDraft] = []
    for document_id in sorted(corpus.documents):
        atoms = [
            partition
            for partition in corpus.ordered(document_id)
            if partition.content.strip()
        ]
        current: list[SourcePartition] = []
        current_tokens = 0
        document_order = 0

        def emit_group(group: Sequence[SourcePartition]) -> None:
            nonlocal document_order
            if not group:
                return
            document_order += 1
            body = "\n\n".join(_partition_text(corpus, source) for source in group)
            drafts.append(
                ChunkDraft(
                    identifier=(
                        f"structural/{group[0].identifier}/{document_order:06d}"
                    ),
                    document_id=document_id,
                    role="ricercabile",
                    order=document_order,
                    content=_chunk_text(corpus, group, body),
                    source_ids=tuple(source.id for source in group),
                )
            )

        for atom in atoms:
            rendered = _partition_text(corpus, atom)
            atom_tokens = len(tokenizer.encode(rendered))
            same_parent = not current or current[-1].parent_id == atom.parent_id
            if current and (
                not same_parent or current_tokens + atom_tokens > config.max_tokens
            ):
                emit_group(current)
                current = []
                current_tokens = 0
            if atom_tokens > config.max_tokens:
                if current:
                    emit_group(current)
                    current = []
                    current_tokens = 0
                for piece in _split_tokens(
                    rendered,
                    size=config.max_tokens,
                    overlap=config.overlap_tokens,
                    encoding=config.encoding,
                ):
                    document_order += 1
                    drafts.append(
                        ChunkDraft(
                            identifier=(
                                f"structural/{atom.identifier}/{document_order:06d}"
                            ),
                            document_id=document_id,
                            role="ricercabile",
                            order=document_order,
                            content=_chunk_text(corpus, [atom], piece),
                            source_ids=(atom.id,),
                        )
                    )
                continue
            current.append(atom)
            current_tokens += atom_tokens
        if current:
            emit_group(current)
    return _attach_parents(corpus, drafts)


def _load_partitions(connection: Connection) -> list[SourcePartition]:
    rows = connection.execute(
        text(
            "SELECT p.id, p.documento_id, d.codice AS documento_codice, "
            "d.titolo AS documento_titolo, p.acquisizione_fonte_id, "
            "a.sha256 AS acquisizione_sha256, p.partizione_genitore_id, "
            "p.identificatore, p.tipo, p.rubrica, p.ordine, p.contenuto "
            "FROM partizioni_documentali AS p "
            "JOIN documenti AS d ON d.id = p.documento_id "
            "JOIN acquisizioni_fonti AS a ON a.id = p.acquisizione_fonte_id "
            "WHERE d.abilitato_per_agente "
            "ORDER BY d.codice, p.id"
        )
    ).mappings()
    return [
        SourcePartition(
            id=int(row["id"]),
            document_id=int(row["documento_id"]),
            document_code=str(row["documento_codice"]),
            document_title=str(row["documento_titolo"]),
            acquisition_id=int(row["acquisizione_fonte_id"]),
            acquisition_sha256=str(row["acquisizione_sha256"]),
            parent_id=(
                int(row["partizione_genitore_id"])
                if row["partizione_genitore_id"] is not None
                else None
            ),
            identifier=str(row["identificatore"]),
            kind=str(row["tipo"]),
            rubric=str(row["rubrica"]) if row["rubrica"] is not None else None,
            order=int(row["ordine"]),
            content=str(row["contenuto"]),
        )
        for row in rows
    ]


def _fingerprint(
    strategy: Strategy,
    config: ChunkingConfig,
    partitions: Sequence[SourcePartition],
) -> str:
    payload = {
        "strategy": strategy,
        "revision": STRATEGY_REVISION,
        "config": asdict(config),
        "partitions": [asdict(partition) for partition in partitions],
    }
    serialized = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _store_drafts(
    connection: Connection,
    set_id: int,
    drafts: Sequence[ChunkDraft],
    partitions: Sequence[SourcePartition],
) -> None:
    sources = {partition.id: partition for partition in partitions}
    chunk_ids: dict[tuple[int, str], int] = {}
    for draft in drafts:
        if draft.role != "parent":
            continue
        chunk_ids[(draft.document_id, draft.identifier)] = _insert_chunk(
            connection, set_id, draft, None
        )
    for draft in drafts:
        if draft.role == "parent":
            continue
        parent_id = (
            chunk_ids.get((draft.document_id, draft.parent_identifier))
            if draft.parent_identifier
            else None
        )
        chunk_ids[(draft.document_id, draft.identifier)] = _insert_chunk(
            connection, set_id, draft, parent_id
        )
    for draft in drafts:
        chunk_id = chunk_ids[(draft.document_id, draft.identifier)]
        for position, source_id in enumerate(draft.source_ids):
            source = sources[source_id]
            connection.execute(
                text(
                    "INSERT INTO chunk_partizioni "
                    "(chunk_id, posizione, partizione_documentale_id, "
                    " acquisizione_fonte_id, identificatore_partizione, sha256_contenuto) "
                    "VALUES (:chunk_id, :position, :partition_id, :acquisition_id, "
                    " :identifier, :content_hash)"
                ),
                {
                    "chunk_id": chunk_id,
                    "position": position,
                    "partition_id": source.id,
                    "acquisition_id": source.acquisition_id,
                    "identifier": source.identifier,
                    "content_hash": hashlib.sha256(source.content.encode()).hexdigest(),
                },
            )


def _insert_chunk(
    connection: Connection,
    set_id: int,
    draft: ChunkDraft,
    parent_id: int | None,
) -> int:
    return int(
        connection.execute(
            text(
                "INSERT INTO chunk "
                "(insieme_chunk_id, documento_id, chunk_genitore_id, identificatore, "
                " ruolo, ordine, contenuto, sha256) "
                "VALUES (:set_id, :document_id, :parent_id, :identifier, :role, "
                " :position, :content, :digest) RETURNING id"
            ),
            {
                "set_id": set_id,
                "document_id": draft.document_id,
                "parent_id": parent_id,
                "identifier": draft.identifier,
                "role": draft.role,
                "position": draft.order,
                "content": draft.content,
                "digest": hashlib.sha256(draft.content.encode()).hexdigest(),
            },
        ).scalar_one()
    )


def generate_chunk_set(strategy: Strategy, config: ChunkingConfig) -> ChunkingReport:
    """Create or reuse one immutable chunk set for the enabled corpus."""
    config.validate()
    try:
        engine = create_engine(database_url())
    except RuntimeError as error:
        raise ChunkingError(str(error)) from error
    try:
        with engine.begin() as connection:
            partitions = _load_partitions(connection)
            if not partitions:
                raise ChunkingError("Il corpus abilitato non contiene partizioni.")
            fingerprint = _fingerprint(strategy, config, partitions)
            existing = connection.execute(
                text("SELECT id FROM insiemi_chunk WHERE fingerprint = :fingerprint"),
                {"fingerprint": fingerprint},
            ).scalar_one_or_none()
            if existing is not None:
                ensure_bm25_index(connection, int(existing))
                counts = (
                    connection.execute(
                        text(
                            "SELECT count(*) AS chunks, "
                            "count(*) FILTER (WHERE ruolo = 'parent') AS parents "
                            "FROM chunk WHERE insieme_chunk_id = :set_id"
                        ),
                        {"set_id": existing},
                    )
                    .mappings()
                    .one()
                )
                return ChunkingReport(
                    int(existing),
                    strategy,
                    int(counts["chunks"]),
                    int(counts["parents"]),
                    True,
                )
            drafts = (
                generate_fixed(partitions, config)
                if strategy == "fixed"
                else generate_structural(partitions, config)
            )
            set_id = int(
                connection.execute(
                    text(
                        "INSERT INTO insiemi_chunk "
                        "(strategia, revisione, configurazione, fingerprint) "
                        "VALUES (:strategy, :revision, CAST(:config AS jsonb), :fingerprint) "
                        "RETURNING id"
                    ),
                    {
                        "strategy": strategy,
                        "revision": STRATEGY_REVISION,
                        "config": json.dumps(asdict(config), sort_keys=True),
                        "fingerprint": fingerprint,
                    },
                ).scalar_one()
            )
            _store_drafts(connection, set_id, drafts, partitions)
            ensure_bm25_index(connection, set_id)
            parents = sum(draft.role == "parent" for draft in drafts)
            return ChunkingReport(set_id, strategy, len(drafts), parents, False)
    finally:
        engine.dispose()


def format_report(report: ChunkingReport) -> str:
    state = "riusato" if report.reused else "creato"
    return (
        f"Insieme chunk {report.set_id} {state}: strategia {report.strategy}, "
        f"{report.chunks} chunk ({report.parents} parent)."
    )
