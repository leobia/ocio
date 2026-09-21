"""Command-line interface for OCIO."""

from __future__ import annotations

import argparse


def main() -> int:
    """Run the OCIO command-line interface."""
    parser = argparse.ArgumentParser(description="OCIO backend")
    parser.parse_args()
    return 0
