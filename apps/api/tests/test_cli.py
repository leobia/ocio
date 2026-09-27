"""Public CLI contract tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ocio import cli
from ocio.embeddings import EmbeddingImportReport, EmbeddingReport


def test_help_is_available() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ocio", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "OCIO" in result.stdout
    assert "normalizza-corpus" in result.stdout
    assert "genera-chunk" in result.stdout
    assert "esporta-corpus-valutazione" in result.stdout
    assert "valida-silver-set" in result.stdout
    assert "genera-embedding" in result.stdout
    assert "importa-embedding" in result.stdout


def test_embedding_commands_report_their_results(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache.jsonl.gz"
    monkeypatch.setattr(
        cli,
        "generate_embeddings",
        lambda *_args, **_kwargs: EmbeddingReport(5, 3, 2, 1, cache),
    )
    monkeypatch.setattr(
        sys, "argv", ["ocio", "genera-embedding", "abc", "--model", "small"]
    )
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "Chunk ricercabili: 5" in output
    assert "Contenuti unici: 3" in output
    assert "Embedding riusati: 2" in output
    assert "Embedding creati: 1" in output

    monkeypatch.setattr(
        cli,
        "import_embeddings",
        lambda *_args: EmbeddingImportReport("text-embedding-3-small", 1536, 3),
    )
    monkeypatch.setattr(sys, "argv", ["ocio", "importa-embedding", str(cache)])
    assert cli.main() == 0
    assert "Embedding importati: 3" in capsys.readouterr().out
