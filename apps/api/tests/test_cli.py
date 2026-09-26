"""Public CLI contract tests."""

from __future__ import annotations

import subprocess
import sys


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
