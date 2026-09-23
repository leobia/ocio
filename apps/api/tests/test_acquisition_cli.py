"""Acquisition behavior through the public CLI."""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from ocio.database import database_url

URN = "urn:nir:stato:decreto.legislativo:2008-04-09;81"


@contextmanager
def source_server(content_type: str, payload: bytes) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/source":
                body = (
                    b'<html><a href="/do/atto/caricaAKN?dataGU=20080430'
                    b'&amp;codiceRedaz=008G0104&amp;dataVigenza=20260923">'
                    b'esporta in Akoma ntoso</a></html>'
                )
                response_type = "text/html"
            else:
                body = payload
                response_type = content_type
            self.send_response(200)
            self.send_header("Content-Type", response_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/source"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def run_import(tmp_path: Path, source_url: str) -> subprocess.CompletedProcess[str]:
    registry = tmp_path / "ocio_sources.yaml"
    registry.write_text(
        "version: 2\n"
        "seed_documents:\n"
        "  - id: dlgs_81_2008\n"
        "    primary_provider: normattiva\n"
        f"    source: {source_url}\n"
    )
    return subprocess.run(
        [sys.executable, "-m", "ocio", "importa-dlgs-81", "--sources", str(registry)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_changed_source_format_is_explained(tmp_path: Path) -> None:
    with source_server("application/pdf", b"%PDF-1.7") as source_url:
        result = run_import(tmp_path, source_url)

    assert result.returncode != 0
    assert "formato" in result.stderr.lower()
    assert "AKN" in result.stderr


def test_unexpected_act_is_rejected(tmp_path: Path) -> None:
    payload = (
        b'<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0">'
        b'<act><meta><identification><FRBRWork>'
        b'<FRBRalias name="urn:nir" value="urn:nir:stato:legge:2000-01-01;1"/>'
        b'</FRBRWork></identification></meta>'
        b'<body><article eId="art_1"/><article eId="art_306"/></body>'
        b'</act></akomaNtoso>'
    )
    with source_server("text/xml", payload) as source_url:
        result = run_import(tmp_path, source_url)

    assert result.returncode != 0
    assert "D.Lgs. 81/2008" in result.stderr


@pytest.mark.integration
def test_import_is_idempotent_by_content_hash(tmp_path: Path) -> None:
    try:
        engine = create_engine(database_url())
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")

    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0">'
        '<act><meta><identification><FRBRWork>'
        f'<FRBRalias name="urn:nir" value="{URN}"/>'
        '</FRBRWork></identification></meta>'
        '<body><article eId="art_1"/><article eId="art_306"/></body>'
        f'</act><!-- {tmp_path} --></akomaNtoso>'
    ).encode()

    with source_server("text/xml", payload) as source_url:
        first = run_import(tmp_path, source_url)
        second = run_import(tmp_path, source_url)

    try:
        assert first.returncode == 0, first.stderr
        assert "acquisita" in first.stdout.lower()
        assert second.returncode == 0, second.stderr
        assert "già presente" in second.stdout.lower()
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM acquisizioni_fonti WHERE fonte = 'Normattiva' AND sha256 = :sha256"),
                {"sha256": sha256(payload).hexdigest()},
            )
        engine.dispose()
