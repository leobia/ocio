"""Evidence acquisition for an engagement, separate from normative conversations."""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Protocol
from uuid import UUID, uuid4

import pdfplumber
from openai import OpenAI
from PIL import Image, UnidentifiedImageError
from sqlalchemy import Engine, text

ANALYSIS_VERSION = "engagement-evidence-v1"
SUPPORTED = {"image/jpeg", "image/png", "image/webp", "application/pdf", "text/plain"}


class EvidenceAnalyzer(Protocol):
    def analyze(
        self, content: bytes, media_type: str, instruction: str, sections: Sequence[str]
    ) -> tuple[str, list[dict[str, str]]]: ...


class OpenAIEvidenceAnalyzer:
    def analyze(
        self, content: bytes, media_type: str, instruction: str, sections: Sequence[str]
    ) -> tuple[str, list[dict[str, str]]]:
        if media_type not in SUPPORTED:
            raise ValueError("Formato non supportato. Usa JPEG, PNG, WebP, PDF o testo semplice.")
        if media_type == "text/plain":
            source = content.decode("utf-8")
            if not source.strip():
                raise ValueError("Il documento di testo è vuoto.")
            passages = f"[testo, righe 1+]\n{source}"
            method = "openai-documento-testo"
        elif media_type == "application/pdf":
            try:
                with pdfplumber.open(BytesIO(content)) as pdf:
                    pages = [
                        f"[pagina {index}]\n{page.extract_text() or '[nessun testo estraibile]'}"
                        for index, page in enumerate(pdf.pages, 1)
                    ]
            except Exception as error:
                raise ValueError("PDF non leggibile.") from error
            passages = "\n\n".join(pages)
            if not pages or all("[nessun testo estraibile]" in page for page in pages):
                raise ValueError("Il PDF non contiene testo estraibile.")
            method = "pdfplumber+openai-documento"
        else:
            try:
                with Image.open(BytesIO(content)) as image:
                    image.verify()
                    if image.format != {
                        "image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP",
                    }[media_type]:
                        raise ValueError("Il formato dichiarato non corrisponde all'immagine.")
            except (UnidentifiedImageError, OSError) as error:
                raise ValueError("Immagine non leggibile.") from error
            passages = ""
            method = "openai-visione"

        if len(passages) > 60_000:
            raise ValueError("Documento troppo lungo per un'analisi completa (limite: 60.000 caratteri).")

        is_image = media_type.startswith("image/")
        prompt = (
            "Analizza esclusivamente l'evidenza fornita e rispondi in italiano. "
            "Per ogni informazione richiesta restituisci un esito: osservato, "
            "non_leggibile o non_determinabile. Mantieni incertezze e limiti. "
            "Non dedurre conformità, assenza di rischi o fatti non visibili. "
            "Per i documenti indica sempre la pagina o il passaggio di origine "
            "per ogni osservazione; non aggiungere informazioni senza riferimento. "
            "La sezione può essere solo uno dei titoli forniti oppure null. "
            "Restituisci JSON con chiave observations, un array di oggetti con "
            "information, status, text, position, section. position e section "
            "possono essere null solo quando non applicabili."
        )
        user_text = json.dumps({
            "instruction": instruction, "sections": list(sections),
            "document": passages if not is_image else None,
        }, ensure_ascii=False)
        user_content: Any = [{"type": "input_text", "text": user_text}]
        if is_image:
            image_url = f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}"
            user_content.append({"type": "input_image", "image_url": image_url})
        model = os.environ.get("OCIO_EVIDENCE_MODEL", "gpt-4.1-mini")
        response = OpenAI().responses.create(
            model=model,
            instructions=prompt,
            input=[{"role": "user", "content": user_content}],
            text={"format": {"type": "json_object"}},
            store=False,
        )
        value = json.loads(response.output_text)
        items = value.get("observations")
        if not isinstance(items, list) or not items:
            raise ValueError("L'analisi non ha restituito osservazioni valide.")
        result = []
        for item in items:
            if not isinstance(item, dict) or item.get("status") not in (
                "osservato", "non_leggibile", "non_determinabile"
            ):
                raise ValueError("L'analisi ha restituito un esito non valido.")
            information = item.get("information")
            description = item.get("text")
            position = item.get("position")
            if not isinstance(information, str) or not information.strip() or not isinstance(description, str) or not description.strip():
                raise ValueError("L'analisi ha restituito un'osservazione incompleta.")
            if not is_image and (not isinstance(position, str) or not position.strip()):
                raise ValueError("L'analisi del documento non indica la posizione di origine.")
            if media_type == "application/pdf" and isinstance(position, str) and not re.search(r"\bpagina\s+\d+\b", position, re.IGNORECASE):
                raise ValueError("L'analisi del PDF non indica la pagina di origine.")
            section = item.get("section")
            result.append({
                "information": information, "status": item["status"],
                "text": description, "position": position if isinstance(position, str) else "",
                "section": section if section in sections else "",
            })
        return f"{method}:{model}", result


class EvidenceStore(Protocol):
    def add_message(self, engagement_id: UUID, content: str, files: Sequence[tuple[str, str, bytes, str]]) -> dict[str, Any] | None: ...
    def messages(self, engagement_id: UUID) -> list[dict[str, Any]] | None: ...
    def attachment(self, engagement_id: UUID, attachment_id: UUID) -> tuple[str, str, bytes] | None: ...
    def record_analysis(self, engagement_id: UUID, message_id: UUID, attachment_id: UUID, instruction: str, method: str, observations: Sequence[Mapping[str, str]]) -> None: ...
    def record_error(self, engagement_id: UUID, attachment_id: UUID, error: str) -> None: ...
    def link_section(self, engagement_id: UUID, observation_id: UUID, section: str | None) -> bool: ...
    def record_note(self, engagement_id: UUID, message_id: UUID, content: str) -> None: ...


class PostgresEvidenceStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add_message(self, engagement_id: UUID, content: str, files: Sequence[tuple[str, str, bytes, str]]) -> dict[str, Any] | None:
        message_id = uuid4()
        with self.engine.begin() as connection:
            exists = connection.execute(text("SELECT 1 FROM incarichi WHERE id = :id"), {"id": engagement_id}).scalar_one_or_none()
            if exists is None:
                return None
            connection.execute(text(
                "INSERT INTO messaggi_incarico (id, incarico_id, contenuto) VALUES (:id, :engagement_id, :content)"
            ), {"id": message_id, "engagement_id": engagement_id, "content": content})
            for name, media_type, data, instruction in files:
                connection.execute(text(
                    "INSERT INTO allegati_incarico (id, messaggio_id, nome, tipo, istruzione, contenuto) "
                    "VALUES (:id, :message_id, :name, :media_type, :instruction, :data)"
                ), {"id": uuid4(), "message_id": message_id, "name": name, "media_type": media_type, "instruction": instruction, "data": data})
        return next(item for item in self.messages(engagement_id) or [] if item["id"] == str(message_id))

    def messages(self, engagement_id: UUID) -> list[dict[str, Any]] | None:
        with self.engine.connect() as connection:
            exists = connection.execute(text("SELECT 1 FROM incarichi WHERE id = :id"), {"id": engagement_id}).scalar_one_or_none()
            if exists is None:
                return None
            rows = connection.execute(text(
                "SELECT id, contenuto, creato_il FROM messaggi_incarico "
                "WHERE incarico_id = :id ORDER BY creato_il, id"
            ), {"id": engagement_id}).mappings().all()
            result = []
            for row in rows:
                attachments = connection.execute(text(
                    "SELECT id, nome, tipo, istruzione, octet_length(contenuto) AS size, stato, errore "
                    "FROM allegati_incarico WHERE messaggio_id = :id ORDER BY creato_il, id"
                ), {"id": row["id"]}).mappings().all()
                observations = connection.execute(text(
                    "SELECT id, allegato_id, sezione, informazione, esito, testo, posizione, "
                    "istruzione, metodo, versione FROM osservazioni_incarico "
                    "WHERE messaggio_id = :id ORDER BY creata_il, id"
                ), {"id": row["id"]}).mappings().all()
                result.append({
                    "id": str(row["id"]), "content": row["contenuto"], "created_at": row["creato_il"],
                    "attachments": [{
                        "id": str(item["id"]), "name": item["nome"], "media_type": item["tipo"],
                        "instruction": item["istruzione"],
                        "size": item["size"], "status": item["stato"], "error": item["errore"],
                    } for item in attachments],
                    "observations": [_observation_dict(item) for item in observations],
                })
        return result

    def attachment(self, engagement_id: UUID, attachment_id: UUID) -> tuple[str, str, bytes] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT a.nome, a.tipo, a.contenuto FROM allegati_incarico a "
                "JOIN messaggi_incarico m ON m.id = a.messaggio_id "
                "WHERE a.id = :id AND m.incarico_id = :engagement_id"
            ), {"id": attachment_id, "engagement_id": engagement_id}).one_or_none()
            return (row[0], row[1], bytes(row[2])) if row else None

    def record_analysis(self, engagement_id: UUID, message_id: UUID, attachment_id: UUID, instruction: str, method: str, observations: Sequence[Mapping[str, str]]) -> None:
        with self.engine.begin() as connection:
            for item in observations:
                connection.execute(text(
                    "INSERT INTO osservazioni_incarico (id, messaggio_id, allegato_id, sezione, "
                    "informazione, esito, testo, posizione, istruzione, metodo, versione) "
                    "VALUES (:id, :message_id, :attachment_id, :section, :information, :status, "
                    ":description, :position, :instruction, :method, :version)"
                ), {
                    "id": uuid4(), "message_id": message_id, "attachment_id": attachment_id,
                    "section": item.get("section") or None, "information": item["information"],
                    "status": item["status"], "description": item["text"],
                    "position": item.get("position") or None, "instruction": instruction,
                    "method": method, "version": ANALYSIS_VERSION,
                })
            connection.execute(text(
                "UPDATE allegati_incarico SET stato = 'analizzato', errore = NULL "
                "WHERE id = :id AND messaggio_id = :message_id"
            ), {"id": attachment_id, "message_id": message_id})

    def record_error(self, engagement_id: UUID, attachment_id: UUID, error: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE allegati_incarico a SET stato = 'errore', errore = :error "
                "FROM messaggi_incarico m WHERE a.id = :id AND a.messaggio_id = m.id "
                "AND m.incarico_id = :engagement_id"
            ), {"id": attachment_id, "engagement_id": engagement_id, "error": error[:500]})

    def link_section(self, engagement_id: UUID, observation_id: UUID, section: str | None) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(text(
                "UPDATE osservazioni_incarico o SET sezione = :section "
                "FROM messaggi_incarico m WHERE o.id = :id AND o.messaggio_id = m.id "
                "AND m.incarico_id = :engagement_id"
            ), {"section": section, "id": observation_id, "engagement_id": engagement_id})
            return result.rowcount == 1

    def record_note(self, engagement_id: UUID, message_id: UUID, content: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO osservazioni_incarico (id, messaggio_id, informazione, esito, "
                "testo, istruzione, metodo, versione) VALUES "
                "(:id, :message_id, 'Appunto dell’operatore', 'osservato', "
                ":content, :content, 'appunto-originale', :version)"
            ), {"id": uuid4(), "message_id": message_id, "content": content,
                "version": ANALYSIS_VERSION})


def _observation_dict(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item["id"]), "attachment_id": str(item["allegato_id"]) if item["allegato_id"] else None,
        "section": item["sezione"], "information": item["informazione"],
        "status": item["esito"], "text": item["testo"], "position": item["posizione"],
        "instruction": item["istruzione"], "method": item["metodo"], "version": item["versione"],
    }


class MemoryEvidenceStore:
    """Small test adapter with the same engagement boundary as the database store."""

    def __init__(self) -> None:
        self.engagements: set[UUID] = set()
        self.data: dict[UUID, list[dict[str, Any]]] = {}
        self.files: dict[UUID, tuple[UUID, str, str, bytes]] = {}

    def add_message(self, engagement_id: UUID, content: str, files: Sequence[tuple[str, str, bytes, str]]) -> dict[str, Any] | None:
        if engagement_id not in self.engagements:
            return None
        value: dict[str, Any] = {
            "id": str(uuid4()), "content": content, "created_at": datetime.now(UTC),
            "attachments": [], "observations": [],
        }
        for name, media_type, data, instruction in files:
            attachment_id = uuid4()
            self.files[attachment_id] = engagement_id, name, media_type, data
            value["attachments"].append({
                "id": str(attachment_id), "name": name, "media_type": media_type,
                "instruction": instruction,
                "size": len(data), "status": "in_attesa", "error": None,
            })
        self.data.setdefault(engagement_id, []).append(value)
        return value

    def messages(self, engagement_id: UUID) -> list[dict[str, Any]] | None:
        return self.data.setdefault(engagement_id, []) if engagement_id in self.engagements else None

    def attachment(self, engagement_id: UUID, attachment_id: UUID) -> tuple[str, str, bytes] | None:
        item = self.files.get(attachment_id)
        return item[1:] if item and item[0] == engagement_id else None

    def record_analysis(self, engagement_id: UUID, message_id: UUID, attachment_id: UUID, instruction: str, method: str, observations: Sequence[Mapping[str, str]]) -> None:
        item = next(item for item in self.data[engagement_id] if item["id"] == str(message_id))
        attachment = next(item for item in item["attachments"] if item["id"] == str(attachment_id))
        attachment.update(status="analizzato", error=None)
        for observation in observations:
            item["observations"].append({
                "id": str(uuid4()), "attachment_id": str(attachment_id),
                "section": observation.get("section") or None, "information": observation["information"],
                "status": observation["status"], "text": observation["text"],
                "position": observation.get("position") or None, "instruction": instruction,
                "method": method, "version": ANALYSIS_VERSION,
            })

    def record_error(self, engagement_id: UUID, attachment_id: UUID, error: str) -> None:
        for message in self.data[engagement_id]:
            for attachment in message["attachments"]:
                if attachment["id"] == str(attachment_id):
                    attachment.update(status="errore", error=error[:500])

    def link_section(self, engagement_id: UUID, observation_id: UUID, section: str | None) -> bool:
        for message in self.data.get(engagement_id, []):
            for item in message["observations"]:
                if item["id"] == str(observation_id):
                    item["section"] = section
                    return True
        return False

    def record_note(self, engagement_id: UUID, message_id: UUID, content: str) -> None:
        item = next(item for item in self.data[engagement_id] if item["id"] == str(message_id))
        item["observations"].append({
            "id": str(uuid4()), "attachment_id": None, "section": None,
            "information": "Appunto dell’operatore", "status": "osservato",
            "text": content, "position": None, "instruction": content,
            "method": "appunto-originale", "version": ANALYSIS_VERSION,
        })
