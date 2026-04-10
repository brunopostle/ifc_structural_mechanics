"""Tests for multi-step *STEP-per-load-case writing in write_analysis_steps()."""

import io


from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    write_analysis_steps,
)
from ifc_structural_mechanics.domain.load import LoadGroup, PointLoad
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel


def _make_model_with_load_cases(n_cases: int = 2, gravity: bool = False):
    """Build a minimal StructuralModel with n_cases load cases, each having one PointLoad."""
    model = StructuralModel(id="test_model")

    # Add a minimal curve member so material validation passes
    mat = Material(
        id="mat1",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )
    sec = Section.create_rectangular_section(
        id="sec1", name="Rect", width=0.1, height=0.2
    )
    member = CurveMember(
        id="m1",
        geometry=[[0, 0, 0], [1, 0, 0]],
        material=mat,
        section=sec,
    )
    model.add_member(member)

    for i in range(n_cases):
        load = PointLoad(
            id=f"load_{i}",
            magnitude=float((i + 1) * 1000),
            direction=[0, 0, -1],
            position=[float(i), 0.0, 3.0],
        )
        case = LoadGroup(id=f"lc_{i}", name=f"Case {i}", is_load_case=True)
        case.add_load(load)
        model.load_groups.append(case)

    return model


class TestMultiStepWriting:
    """write_analysis_steps() one-step-per-load-case behaviour."""

    def test_two_load_cases_produce_two_steps(self):
        """Two load cases → exactly two *STEP/*END STEP pairs."""
        model = _make_model_with_load_cases(2)
        buf = io.StringIO()
        node_coords = {1: (0.0, 0.0, 3.0), 2: (1.0, 0.0, 3.0)}
        write_analysis_steps(buf, model, node_coords=node_coords)
        text = buf.getvalue()

        assert text.count("*STEP") == 2
        assert text.count("*END STEP") == 2
        assert text.count("*STATIC") == 2

    def test_each_step_has_correct_load_comment(self):
        """Each step is annotated with its load case name."""
        model = _make_model_with_load_cases(2)
        buf = io.StringIO()
        write_analysis_steps(buf, model)
        text = buf.getvalue()

        assert "** Load Case: Case 0" in text
        assert "** Load Case: Case 1" in text

    def test_gravity_adds_extra_step(self):
        """When gravity=True and load cases exist, a third gravity step is written."""
        model = _make_model_with_load_cases(2)
        buf = io.StringIO()
        write_analysis_steps(buf, model, gravity=True)
        text = buf.getvalue()

        assert text.count("*STEP") == 3
        assert text.count("*END STEP") == 3
        assert "** Gravity (self-weight)" in text
        assert "GRAV" in text

    def test_gravity_step_has_no_cload(self):
        """The gravity step must not repeat *CLOAD loads."""
        model = _make_model_with_load_cases(1)
        buf = io.StringIO()
        write_analysis_steps(buf, model, gravity=True)
        text = buf.getvalue()

        # Split on steps
        steps = text.split("*END STEP")
        gravity_step = steps[-2]  # last step before final empty fragment
        assert "*CLOAD" not in gravity_step
        assert "GRAV" in gravity_step

    def test_no_load_cases_falls_back_to_single_step(self):
        """Without load cases, a single combined step is written (backward compat)."""
        model = StructuralModel(id="test_model")
        mat = Material(
            id="mat1",
            name="Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
        )
        sec = Section.create_rectangular_section(
            id="s1", name="R", width=0.1, height=0.2
        )
        member = CurveMember(
            id="m1", geometry=[[0, 0, 0], [1, 0, 0]], material=mat, section=sec
        )
        model.add_member(member)

        # Add a non-load-case group
        sub = LoadGroup(id="sg1", name="Sub-group", is_load_case=False)
        load = PointLoad(
            id="p1", magnitude=500.0, direction=[0, 0, -1], position=[0.5, 0, 0]
        )
        sub.add_load(load)
        model.load_groups.append(sub)

        buf = io.StringIO()
        write_analysis_steps(buf, model)
        text = buf.getvalue()

        assert text.count("*STEP") == 1
        assert text.count("*END STEP") == 1

    def test_gravity_only_single_step(self):
        """gravity=True with no load cases → single step with GRAV."""
        model = StructuralModel(id="test_model")
        mat = Material(
            id="m1", name="S", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
        )
        sec = Section.create_rectangular_section(
            id="s1", name="R", width=0.1, height=0.2
        )
        model.add_member(
            CurveMember(
                id="c1", geometry=[[0, 0, 0], [1, 0, 0]], material=mat, section=sec
            )
        )

        buf = io.StringIO()
        write_analysis_steps(buf, model, gravity=True)
        text = buf.getvalue()

        assert text.count("*STEP") == 1
        assert "GRAV" in text
