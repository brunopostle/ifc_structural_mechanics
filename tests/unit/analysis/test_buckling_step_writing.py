"""Tests for linear buckling INP step writing."""

import io

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    write_analysis_steps,
)
from ifc_structural_mechanics.domain.load import LoadGroup, PointLoad
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel


def _buckling_model():
    """Minimal model with one load for buckling tests."""
    model = StructuralModel(id="buckle_model")
    mat = Material(
        id="mat1",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )
    sec = Section.create_rectangular_section(
        id="sec1", name="Rect", width=0.05, height=0.05
    )
    model.add_member(
        CurveMember(id="m1", geometry=[[0, 0, 0], [0, 0, 2]], material=mat, section=sec)
    )
    load = PointLoad(id="p1", magnitude=1.0, direction=[0, 0, -1], position=[0, 0, 2])
    group = LoadGroup(id="lg1", name="Buckling Load", is_load_case=True)
    group.add_load(load)
    model.load_groups.append(group)
    return model


class TestBucklingStepWriting:
    """write_analysis_steps() with analysis_type='linear_buckling'."""

    def _get_text(self, model=None, **kwargs):
        model = model or _buckling_model()
        buf = io.StringIO()
        write_analysis_steps(buf, model, analysis_type="linear_buckling", **kwargs)
        return buf.getvalue()

    def test_single_step_block(self):
        """Buckling analysis is one *STEP/*END STEP pair."""
        text = self._get_text()
        assert text.count("*STEP") == 1
        assert text.count("*END STEP") == 1

    def test_no_static_prestress_step(self):
        """No *STATIC step: loads there would be preload, not reference load."""
        text = self._get_text()
        assert "*STATIC" not in text
        assert "PERTURBATION" not in text

    def test_buckle_keyword_present_once(self):
        """*BUCKLE must appear exactly once."""
        text = self._get_text()
        assert text.count("*BUCKLE") == 1

    def test_loads_are_inside_buckle_step(self):
        """Reference loads must follow *BUCKLE and precede *END STEP.

        CalculiX only scales loads defined inside the buckle step; a buckle step
        with no loads of its own returns meaningless factors.
        """
        text = self._get_text(gravity=True)
        buckle = text.index("*BUCKLE")
        end = text.index("*END STEP")
        assert buckle < text.index("*DLOAD") < end
