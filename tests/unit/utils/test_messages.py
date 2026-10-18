"""The codes of warnings and errors: registered, used, documented (94g.12)."""

import ast
import re
import shutil
from pathlib import Path

import pytest

from ifc_structural_mechanics.utils.error_handling import AnalysisError
from ifc_structural_mechanics.utils.messages import (
    KINDS,
    STAGES,
    render_markdown,
    warning,
)

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "src" / "ifc_structural_mechanics"
CODE = re.compile(r"\"([WE]-[A-Z]{3}-\d{3})\"")
ERRORS = {
    "AnalysisError",
    "MeshingError",
    "ModelExtractionError",
    "ResultProcessingError",
    "StructuralAnalysisError",
}


def _codes_used():
    used = set()
    for path in SOURCE.rglob("*.py"):
        if path.name == "messages.py":
            continue
        used.update(CODE.findall(path.read_text()))
    return used


def test_every_code_used_is_registered():
    assert _codes_used() - set(KINDS) == set()


def test_every_registered_code_is_used():
    assert set(KINDS) - _codes_used() == set()


def test_codes_are_numbered_from_one_in_each_stage():
    for stage in STAGES:
        for kind in "WE":
            numbers = [
                int(code[-3:]) for code in KINDS if code.startswith(f"{kind}-{stage}-")
            ]
            assert numbers == list(range(1, len(numbers) + 1)), (kind, stage)
    assert {code.split("-")[1] for code in KINDS} <= set(STAGES)


def test_every_error_raised_has_a_code():
    """A wrapper passes on the code of the error it wraps."""
    missing = []
    for path in SOURCE.rglob("*.py"):
        source = path.read_text()
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            func = node.exc.func
            if getattr(func, "id", getattr(func, "attr", None)) not in ERRORS:
                continue
            code = next((k.value for k in node.exc.keywords if k.arg == "code"), None)
            if isinstance(code, ast.Constant) and code.value in KINDS:
                continue
            if ast.unparse(code or ast.Constant(None)) == "error.code":
                continue
            missing.append(f"{path.relative_to(SOURCE)}:{node.lineno}")
    assert missing == []


def test_an_error_shows_its_code():
    error = AnalysisError("Support s cannot be applied.", code="E-SUP-002")
    assert error.code == "E-SUP-002"
    assert "[E-SUP-002] Support s" in str(error)
    assert error.to_dict()["code"] == "E-SUP-002"


def test_docs_are_up_to_date():
    """Rewrite with python -m ifc_structural_mechanics.utils.messages."""
    written = (ROOT / "docs" / "messages.md").read_text()
    assert written == render_markdown()


def test_a_warning_carries_its_code_and_title():
    found = warning("W-SUP-001", "2 member(s) ...", ifc_guids=["a", "b"])
    assert found["code"] == "W-SUP-001"
    assert found["title"] == KINDS["W-SUP-001"].title
    assert found["severity"] == "warning"
    assert found["ifc_guids"] == ["a", "b"]


def test_an_unregistered_code_is_refused():
    with pytest.raises(KeyError):
        warning("W-SUP-999", "...")


def test_every_warning_of_an_analysis_has_a_code(tmp_path):
    """beam_01 as a buckling run warns from the writer and the API."""
    path = ROOT / "examples" / "analysis-models" / "ifcFiles" / "beam_01.ifc"
    if not path.exists():
        pytest.skip("example models submodule missing")
    if shutil.which("ccx") is None:
        pytest.skip("CalculiX (ccx) not installed")
    from ifc_structural_mechanics.api.structural_analysis import analyze_ifc

    result = analyze_ifc(
        str(path), str(tmp_path), analysis_type="linear_buckling", mesh_size=0.5
    )
    codes = [found.get("code") for found in result["warnings"]]
    assert "W-LOD-006" in codes
    assert all(code in KINDS for code in codes), codes
