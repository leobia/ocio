"""Command-line interface for OCIO."""

from __future__ import annotations

import argparse
from pathlib import Path

from ocio.acquisition import AcquisitionError, import_source_acquisitions
from ocio.chunking import (
    ChunkingConfig,
    ChunkingError,
    generate_chunk_set,
)
from ocio.chunking import (
    format_report as format_chunking_report,
)
from ocio.normalization import NormalizationError, format_report, normalize_corpus


def main() -> int:
    """Run the OCIO command-line interface."""
    parser = argparse.ArgumentParser(description="OCIO backend")
    commands = parser.add_subparsers(dest="command")
    importer = commands.add_parser(
        "importa-corpus", help="Importa le acquisizioni locali del corpus"
    )
    importer.add_argument(
        "--sources",
        type=Path,
        default=Path(__file__).resolve().parents[4] / "ocio_sources.yaml",
        help="Percorso del registro delle fonti",
    )
    normalizer = commands.add_parser(
        "normalizza-corpus",
        help="Normalizza il corpus locale in partizioni documentali",
    )
    normalizer.add_argument(
        "--sources",
        type=Path,
        default=Path(__file__).resolve().parents[4] / "ocio_sources.yaml",
        help="Percorso del registro delle fonti",
    )
    chunker = commands.add_parser(
        "genera-chunk", help="Genera un insieme versionato di chunk"
    )
    chunker.add_argument("strategy", choices=("fixed", "structural"))
    chunker.add_argument("--max-tokens", type=int, default=512)
    chunker.add_argument("--overlap-tokens", type=int, default=0)
    chunker.add_argument("--encoding", default="cl100k_base")
    args = parser.parse_args()
    if args.command == "importa-corpus":
        try:
            total = import_source_acquisitions(args.sources)
        except AcquisitionError as error:
            parser.exit(1, f"Importazione fallita: {error}\n")
        print(f"Corpus importato: {total} acquisizioni locali verificate.")
    elif args.command == "normalizza-corpus":
        try:
            normalization_report = normalize_corpus(args.sources)
        except NormalizationError as error:
            parser.exit(1, f"Normalizzazione fallita: {error}\n")
        print(format_report(normalization_report))
    elif args.command == "genera-chunk":
        try:
            chunking_report = generate_chunk_set(
                args.strategy,
                ChunkingConfig(args.max_tokens, args.overlap_tokens, args.encoding),
            )
        except ChunkingError as error:
            parser.exit(1, f"Generazione chunk fallita: {error}\n")
        print(format_chunking_report(chunking_report))
    return 0
