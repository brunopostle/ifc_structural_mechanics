"""Tests for the step of a modal analysis (lon)."""

import io

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    write_analysis_steps,
)
from tests.unit.analysis.test_buckling_step_writing import _buckling_model


def _text(**kwargs) -> str:
    buf = io.StringIO()
    write_analysis_steps(
        buf,
        _buckling_model(),
        analysis_type="modal",
        node_coords={1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 2.0)},
        **kwargs,
    )
    return buf.getvalue()


def test_one_frequency_step_with_the_modes_asked_for():
    text = _text(num_modes=7)
    assert text.count("*STEP") == 1 and text.count("*END STEP") == 1
    assert "*FREQUENCY\n7\n" in text


def test_no_load_is_applied():
    """The model's load case and gravity are not mass, and not written."""
    text = _text(gravity=True)
    assert "*CLOAD" not in text
    assert "*DLOAD" not in text
    assert "*STATIC" not in text


def test_shapes_are_written_to_the_result_file():
    text = _text()
    frequency = text.index("*FREQUENCY")
    assert frequency < text.index("*NODE FILE\nU\n") < text.index("*END STEP")
