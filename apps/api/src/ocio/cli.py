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
from ocio.evaluation import (
    EvaluationError,
    default_schema_path,
    export_evaluation_corpus,
    format_export_report,
    format_validation_report,
    validate_silver_set,
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
    corpus_exporter = commands.add_parser(
        "esporta-corpus-valutazione",
        help="Esporta il corpus compatto per generare il silver set",
    )
    corpus_exporter.add_argument("output", type=Path)
    silver_validator = commands.add_parser(
        "valida-silver-set",
        help="Valida un silver set JSONL contro il corpus canonico",
    )
    silver_validator.add_argument("dataset", type=Path)
    silver_validator.add_argument(
        "--schema",
        type=Path,
        default=default_schema_path(),
        help="Percorso del JSON Schema del silver set",
    )
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
    elif args.command == "esporta-corpus-valutazione":
        try:
            export_report = export_evaluation_corpus(args.output)
        except EvaluationError as error:
            parser.exit(1, f"Esportazione fallita: {error}\n")
        print(format_export_report(export_report))
    elif args.command == "valida-silver-set":
        try:
            validation_report = validate_silver_set(args.dataset, args.schema)
        except EvaluationError as error:
            parser.exit(1, f"Validazione fallita: {error}\n")
        if not validation_report.valid:
            parser.exit(1, format_validation_report(validation_report) + "\n")
        print(format_validation_report(validation_report))
    return 0
