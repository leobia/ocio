"""Offline tests for the versioned chat runtime configuration."""

from pathlib import Path

import pytest

from ocio.chat_runtime import (
    DEFAULT_CONFIG,
    ChatConfigurationError,
    backend_from_environment,
    load_profile,
)


def test_versioned_profiles_define_economy_and_alpha_choices() -> None:
    local = load_profile(DEFAULT_CONFIG, "local")
    alpha = load_profile(DEFAULT_CONFIG, "alpha")
    escalated = load_profile(DEFAULT_CONFIG, "alpha-escalated")

    assert local.generation_model == "gpt-6-luna"
    assert local.reranker is None
    assert alpha.generation_model == "gpt-6-luna"
    assert alpha.reranker == "cohere"
    assert alpha.candidate_k == 20
    assert alpha.top_k == 10
    assert escalated.reranker == alpha.reranker
    assert escalated.generation_model == "gpt-6-sol"


def test_runtime_stays_unconfigured_without_an_explicit_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCIO_CHAT_PROFILE", raising=False)

    assert backend_from_environment(object()) is None  # type: ignore[arg-type]


def test_invalid_profile_is_rejected(tmp_path: Path) -> None:
    configuration = tmp_path / "chat.yaml"
    configuration.write_text("schema_version: 1\nprofiles: {}\n", encoding="utf-8")

    with pytest.raises(ChatConfigurationError):
        load_profile(configuration, "missing")
