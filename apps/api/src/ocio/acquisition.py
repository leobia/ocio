"""Acquire the configured D.Lgs. 81/2008 from Normattiva."""

from __future__ import annotations

import hashlib
import re
from html import unescape
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener
from xml.etree import ElementTree

import yaml
from sqlalchemy import create_engine, text

from ocio.database import database_url

URN = "urn:nir:stato:decreto.legislativo:2008-04-09;81"
AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"


class AcquisitionError(Exception):
    """A source cannot be safely acquired."""


def _configured_url(sources: Path) -> str:
    try:
        registry = yaml.safe_load(sources.read_text(encoding="utf-8"))
        atti_normativi = registry["seed_documents"]
        atto_normativo = next(item for item in atti_normativi if item["id"] == "dlgs_81_2008")
        if atto_normativo["primary_provider"] != "normattiva":
            raise AcquisitionError("Il D.Lgs. 81/2008 deve provenire da Normattiva.")
        url = atto_normativo["source"]
        if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https"):
            raise AcquisitionError("URL Normattiva non valido in ocio_sources.yaml.")
        return url
    except (OSError, yaml.YAMLError, KeyError, StopIteration, TypeError) as error:
        raise AcquisitionError(f"Registro fonti non valido: {sources}") from error


def _download_akn(source_url: str) -> tuple[str, bytes]:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    try:
        with opener.open(Request(source_url), timeout=30) as page:
            if page.headers.get_content_type() != "text/html":
                raise AcquisitionError("Formato della pagina Normattiva cambiato: atteso HTML.")
            html = page.read().decode(page.headers.get_content_charset() or "utf-8")
        link = re.search(r'href="(/do/atto/caricaAKN\?[^"]+)"', html)
        if link is None:
            raise AcquisitionError("Formato della pagina Normattiva cambiato: export AKN non trovato.")
        export_url = urljoin(source_url, unescape(link.group(1)))
        with opener.open(Request(export_url), timeout=60) as response:
            if response.headers.get_content_type() not in ("text/xml", "application/xml"):
                raise AcquisitionError("Formato della fonte cambiato: atteso AKN XML.")
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, UnicodeError) as error:
        raise AcquisitionError(f"Download Normattiva non riuscito: {error}") from error
    return export_url, payload


def _validate_akn(payload: bytes) -> str:
    try:
        content = payload.decode("utf-8")
        root = ElementTree.fromstring(content)
    except (UnicodeError, ElementTree.ParseError) as error:
        raise AcquisitionError("Formato della fonte cambiato: AKN XML non valido.") from error
    if (
        root.tag != f"{AKN}akomaNtoso"
        or root.find(f".//{AKN}FRBRalias[@value='{URN}']") is None
        or root.find(f".//{AKN}article[@eId='art_1']") is None
        or root.find(f".//{AKN}article[@eId='art_306']") is None
    ):
        raise AcquisitionError("Formato o contenuto della fonte cambiato: D.Lgs. 81/2008 AKN incompleto.")
    return content


def import_dlgs_81(sources: Path) -> tuple[bool, str]:
    """Store one immutable acquisition, keyed by source and content hash."""
    source_url = _configured_url(sources)
    export_url, payload = _download_akn(source_url)
    content = _validate_akn(payload)
    digest = hashlib.sha256(payload).hexdigest()
    try:
        engine = create_engine(database_url())
        with engine.begin() as connection:
            created = connection.execute(
                text(
                    "INSERT INTO acquisizioni_fonti (fonte, url, contenuto, sha256) "
                    "VALUES ('Normattiva', :url, :content, :digest) "
                    "ON CONFLICT (fonte, sha256) DO NOTHING RETURNING id"
                ),
                {"url": export_url, "content": content, "digest": digest},
            ).scalar_one_or_none()
        engine.dispose()
    except RuntimeError as error:
        raise AcquisitionError(str(error)) from error
    return created is not None, digest
