from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def config() -> dict[str, object]:
    path = Path(__file__).resolve().parents[1] / "vma_mapping_config.json"
    return json.loads(path.read_text(encoding="utf-8"))
