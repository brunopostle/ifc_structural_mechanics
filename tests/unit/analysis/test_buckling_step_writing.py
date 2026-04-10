"""Tests for linear buckling two-step INP writing."""

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

    def test_two_step_blocks(self):
        """Buckling analysis must produce exactly two *STEP/*END STEP pairs."""
        text = self._get_text()
        assert text.count("*STEP") == 2
        assert text.count("*END STEP") == 2

    def test_first_step_is_static(self):
        """First step must be *STATIC (pre-stress)."""
        text = self._get_text()
        lines = text.splitlines()
        step_lines = [l for l in lines if l.strip().startswith("*STEP")]
        assert step_lines[0].strip() == "*STEP"
        # Next non-empty/non-comment line after *STEP should be *STATIC
        idx = lines.index(step_lines[0])
        for l in lines[idx + 1 :]:
            if l.strip() and not l.strip().startswith("**"):
                assert l.strip() == "*STATIC"
                break

    def test_second_step_has_perturbation(self):
        """Second step must carry PERTURBATION keyword."""
        text = self._get_text()
        step_lines = [
            l.strip() for l in text.splitlines() if l.strip().startswith("*STEP")
        ]
        assert len(step_lines) == 2
        assert "PERTURBATION" in step_lines[1]

    def test_buckle_keyword_present_once(self):
        """*BUCKLE must appear exactly once (in the second step)."""
        text = self._get_text()
        assert text.count("*BUCKLE") == 1

    def test_no_cload_or_dload_after_second_step(self):
        """The perturbation step must not contain *CLOAD or *DLOAD."""
        text = self._get_text()
        # Find content after the second *STEP line
        parts = text.split("*STEP")
        assert len(parts) >= 3  # preamble + step1 + step2
        second_step_content = parts[-1]
        assert "*CLOAD" not in second_step_content
        assert "*DLOAD" not in second_step_content

    def test_static_appears_once(self):
        """*STATIC must appear exactly once (only in the pre-stress step)."""
        text = self._get_text()
        assert text.count("*STATIC") == 1
