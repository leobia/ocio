"""Deterministic tests for the live chat evaluation report."""

import json
from pathlib import Path
from typing import Any

import yaml

from ocio.api import Reply
from ocio.chat_evaluation import run_chat_evaluation


class FakeBackend:
    def answer(self, question: str, history: Any, case_state: Any) -> Reply:
        if question == "Impossibile":
            return Reply("ABSTAIN", "Mancano evidenze.", trace={})
        return Reply(
            "ANSWER",
            "Risposta.",
            (
                {
                    "chunk": {"document_code": "doc", "chunk_identifier": "chunk"},
                    "sources": [{"partition_identifier": "part"}],
                },
            ),
            trace={},
        )


def test_evaluation_compares_profiles_and_scores_answer_and_abstention(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "answer",
                "query": "Domanda",
                "answerable": True,
                "expected_evidence": [
                    {"document_code": "doc", "partition_identifier": "part"}
                ],
            }
        )
        + "\n"
        + json.dumps(
            {
                "id": "abstain",
                "query": "Impossibile",
                "answerable": False,
                "expected_evidence": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    configuration = tmp_path / "evaluation.yaml"
    configuration.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "runtime_config": "unused.yaml",
                "dataset": dataset.name,
                "output": "report.json",
                "profiles": ["economy", "alpha"],
            }
        ),
        encoding="utf-8",
    )

    artifacts = run_chat_evaluation(
        configuration,
        lambda _name: FakeBackend(),
    )

    report = json.loads(artifacts.report.read_text(encoding="utf-8"))
    assert [item["name"] for item in report["profiles"]] == ["economy", "alpha"]
    assert report["profiles"][0]["cases"][0]["passed"] is True
    assert report["profiles"][0]["cases"][1]["passed"] is True
