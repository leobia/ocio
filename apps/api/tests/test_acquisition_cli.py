"""Local source acquisition behavior through the public CLI."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine, text

from ocio import acquisition, cli
from ocio.database import database_url


class InsertResult:
    def scalar_one_or_none(self) -> int:
        return 1


class ImportConnection:
    def __init__(self) -> None:
        self.parameters: list[dict[str, Any]] = []

    def __enter__(self) -> ImportConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _statement: object, parameters: dict[str, Any]) -> InsertResult:
        self.parameters.append(parameters)
        return InsertResult()


class ImportEngine:
    def __init__(self) -> None:
        self.connection = ImportConnection()

    def begin(self) -> ImportConnection:
        return self.connection

    def dispose(self) -> None:
        return None


def create_registry(
    tmp_path: Path, payload: bytes, *, digest: str | None = None
) -> Path:
    local_file = tmp_path / "corpus" / "fonti" / "sample" / "source.html"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(payload)
    document = {
        "id": "sample",
        "title": "Documento di prova",
        "primary_provider": "mlps",
        "source": "https://example.invalid/source",
        "local_path": "corpus/fonti/sample/source.html",
        "format": "html",
        "acquired_on": "2026-09-23",
        "sha256": digest or sha256(payload).hexdigest(),
    }
    registry = tmp_path / "ocio_sources.yaml"
    registry.write_text(yaml.safe_dump({"version": 2, "seed_documents": [document]}))
    return registry


def run_import(monkeypatch: pytest.MonkeyPatch, registry: Path) -> ImportEngine:
    engine = ImportEngine()
    monkeypatch.setattr(acquisition, "database_url", lambda: "postgresql://example")
    monkeypatch.setattr(acquisition, "create_engine", lambda _url: engine)
    monkeypatch.setattr(
        sys, "argv", ["ocio", "importa-corpus", "--sources", str(registry)]
    )
    assert cli.main() == 0
    return engine


def test_cli_imports_the_local_file_and_persists_its_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = b"<!doctype html><html><body>FAQ ufficiale</body></html>"
    registry = create_registry(tmp_path, payload)

    engine = run_import(monkeypatch, registry)

    assert engine.connection.parameters[0]["content"] == payload
    metadata = json.loads(engine.connection.parameters[0]["metadata"])
    assert metadata["id"] == "sample"
    assert metadata["local_path"] == "corpus/fonti/sample/source.html"
    assert metadata["format"] == "html"
    assert metadata["acquired_on"] == "2026-09-23"
    assert engine.connection.parameters[0]["url"] == "https://example.invalid/source"
    assert "importato" in capsys.readouterr().out.lower()


def test_cli_reports_a_missing_local_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = create_registry(tmp_path, b"<!doctype html><html></html>")
    (tmp_path / "corpus/fonti/sample/source.html").unlink()
    monkeypatch.setattr(
        sys, "argv", ["ocio", "importa-corpus", "--sources", str(registry)]
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    assert "file locale mancante" in capsys.readouterr().err.lower()


def test_cli_reports_a_hash_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = create_registry(
        tmp_path, b"<!doctype html><html></html>", digest="0" * 64
    )
    monkeypatch.setattr(
        sys, "argv", ["ocio", "importa-corpus", "--sources", str(registry)]
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    assert "sha-256 diverso" in capsys.readouterr().err.lower()


def test_cli_reports_a_format_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = create_registry(tmp_path, b"%PDF-1.7\n%%EOF", digest=None)
    source_config = yaml.safe_load(registry.read_text())
    source_config["seed_documents"][0]["format"] = "html"
    registry.write_text(yaml.safe_dump(source_config))
    monkeypatch.setattr(
        sys, "argv", ["ocio", "importa-corpus", "--sources", str(registry)]
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    assert "formato inatteso" in capsys.readouterr().err.lower()


def test_cli_reports_a_malformed_source_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = create_registry(tmp_path, b"<!doctype html><html></html>")
    source_config = yaml.safe_load(registry.read_text())
    source_config["seed_documents"][0]["source"] = "https://[invalid"
    registry.write_text(yaml.safe_dump(source_config))
    monkeypatch.setattr(
        sys, "argv", ["ocio", "importa-corpus", "--sources", str(registry)]
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    assert "url della fonte non valido" in capsys.readouterr().err.lower()


def test_checked_in_seed_sources_are_local_and_verified() -> None:
    repository = Path(__file__).resolve().parents[3]
    acquisitions = acquisition.read_source_acquisitions(
        repository / "ocio_sources.yaml"
    )

    assert {item.document_id for item in acquisitions} == {
        "dlgs_81_2008",
        "accordo_59_csr_2025",
        "faq_accordo_59_2025",
        "dm_388_2003",
        "dpr_462_2001",
        "dpr_177_2011",
        "dm_11_04_2011",
        "dm_1_2_3_settembre_2021",
        "dm_13_09_2024",
        "di_30_11_2012",
        "dm_132_2024",
    }
    assert len(acquisitions) == 22
    assert sum(item.document_id == "dm_11_04_2011" for item in acquisitions) == 10
    assert sum(item.document_id == "dm_13_09_2024" for item in acquisitions) == 3
    fire_decrees = next(
        item for item in acquisitions if item.document_id == "dm_1_2_3_settembre_2021"
    )
    assert json.loads(fire_decrees.metadata)["vigenza_per_decreto"] == {
        "dm_1_settembre_2021": "2022-09-25",
        "dm_2_settembre_2021": "2022-10-04",
        "dm_3_settembre_2021": "2022-10-29",
    }
    assert {
        json.loads(item.metadata)["part"]
        for item in acquisitions
        if item.document_id == "dm_13_09_2024"
    } == {
        "Art. 1",
        "Art. 2",
        "Art. 3",
    }


@pytest.mark.integration
def test_import_stores_local_bytes_and_metadata_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")

    payload = f"<!doctype html><html><body>{tmp_path}</body></html>".encode()
    digest = sha256(payload).hexdigest()
    registry = create_registry(tmp_path, payload)
    monkeypatch.setattr(
        sys, "argv", ["ocio", "importa-corpus", "--sources", str(registry)]
    )
    engine = create_engine(url)

    try:
        cli.main()
        assert "1 acquisizioni locali verificate" in capsys.readouterr().out
        with engine.connect() as connection:
            stored = connection.execute(
                text(
                    "SELECT contenuto, metadati, sha256 FROM acquisizioni_fonti "
                    "WHERE fonte = 'Ministero del Lavoro' AND sha256 = :digest"
                ),
                {"digest": digest},
            ).one()
        assert stored.contenuto == payload
        assert stored.metadati["id"] == "sample"
        assert stored.metadati["local_path"] == "corpus/fonti/sample/source.html"
        assert stored.sha256 == digest

        cli.main()
        assert "1 acquisizioni locali verificate" in capsys.readouterr().out
        with engine.connect() as connection:
            count = connection.execute(
                text(
                    "SELECT count(*) FROM acquisizioni_fonti "
                    "WHERE fonte = 'Ministero del Lavoro' AND sha256 = :digest"
                ),
                {"digest": digest},
            ).scalar_one()
        assert count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM acquisizioni_fonti "
                    "WHERE fonte = 'Ministero del Lavoro' AND sha256 = :digest"
                ),
                {"digest": digest},
            )
        engine.dispose()
