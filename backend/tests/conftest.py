from __future__ import annotations

import os

import pytest

from catenax_simplified.config import Settings


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's local ``.env`` and ``CXS_*`` variables out of the tests' settings."""
    for name in os.environ:
        if name.upper().startswith("CXS_"):
            monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
