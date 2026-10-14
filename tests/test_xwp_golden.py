"""Golden file test: the Burgsteinfurt example as XWaermeplan (phase 10).

Compares the key figures of the plan (structure, object counts, sums) with
tests/fixtures/xwp/golden_burgsteinfurt.json, so a change of the mapping
shows up in review. After an intended change, regenerate the file with

    FHEAT_UPDATE_GOLDEN=1 python -m pytest tests/test_xwp_golden.py

and check the diff.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.xwp_golden import burgsteinfurt_plan, key_figures

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "xwp" / "golden_burgsteinfurt.json"

pytest.importorskip("lxml")


@pytest.fixture(scope="module")
def plan():
    return burgsteinfurt_plan()


def test_key_figures_match_the_golden_file(plan):
    figures = json.loads(json.dumps(key_figures(*plan)))  # same types as read from the file
    if os.environ.get("FHEAT_UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(figures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    assert figures == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_example_plan_is_valid(plan):
    from fheat_core.xwp.encode.gml import to_gml, validate_gml

    doc, _ = plan
    assert doc.errors() == []
    assert validate_gml(to_gml(doc)) == []


def test_example_plan_is_valid_json_fg(plan):
    pytest.importorskip("jsonschema")
    from fheat_core.xwp.encode.jsonfg import to_jsonfg, validate_jsonfg

    assert validate_jsonfg(to_jsonfg(plan[0])) == []
