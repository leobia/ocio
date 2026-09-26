"""Command-line interface for OCIO."""

from __future__ import annotations

import argparse
from pathlib import Path

from ocio.acquisition import AcquisitionError, import_source_acquisitions
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
    args = parser.parse_args()
    if args.command == "importa-corpus":
        try:
            total = import_source_acquisitions(args.sources)
        except AcquisitionError as error:
            parser.exit(1, f"Importazione fallita: {error}\n")
        print(f"Corpus importato: {total} acquisizioni locali verificate.")
    elif args.command == "normalizza-corpus":
        try:
            report = normalize_corpus(args.sources)
        except NormalizationError as error:
            parser.exit(1, f"Normalizzazione fallita: {error}\n")
        print(format_report(report))
    return 0
