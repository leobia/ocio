"""Command-line interface for OCIO."""

from __future__ import annotations

import argparse
from pathlib import Path

from ocio.acquisition import AcquisitionError, import_dlgs_81


def main() -> int:
    """Run the OCIO command-line interface."""
    parser = argparse.ArgumentParser(description="OCIO backend")
    commands = parser.add_subparsers(dest="command")
    importer = commands.add_parser("importa-dlgs-81", help="Acquisisce il D.Lgs. 81/2008 da Normattiva")
    importer.add_argument(
        "--sources",
        type=Path,
        default=Path(__file__).resolve().parents[4] / "ocio_sources.yaml",
        help="Percorso del registro delle fonti",
    )
    args = parser.parse_args()
    if args.command == "importa-dlgs-81":
        try:
            created, digest = import_dlgs_81(args.sources)
        except AcquisitionError as error:
            parser.exit(1, f"Acquisizione fallita: {error}\n")
        print(f"Acquisizione {'acquisita' if created else 'già presente'}: {digest}")
    return 0
