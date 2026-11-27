"""Tests for linear buckling INP step writing."""

import io
import re

import pytest

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    write_analysis_steps,
)
from ifc_structural_mechanics.analysis.buckling_loads import buckling_load_sets
from ifc_structural_mechanics.domain.load import LoadCombination, LoadGroup, PointLoad
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
        kwargs.setdefault("node_coords", {1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 2.0)})
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
        model = _buckling_model()
        model.load_groups[0].self_weight_coefficients = [0.0, 0.0, -1.0]
        text = self._get_text(model)
        buckle = text.index("*BUCKLE")
        end = text.index("*END STEP")
        assert buckle < text.index("*CLOAD") < end
        assert buckle < text.index("*DLOAD") < end

    def test_gravity_is_a_step_of_its_own(self):
        """--gravity is a load case no combination includes, as in a static
        analysis."""
        text = self._get_text(gravity=True)
        first, second = text.split("*END STEP")[:2]
        assert "*CLOAD" in first and "*DLOAD" not in first
        assert "*DLOAD" in second and "*CLOAD" not in second


def _two_cases():
    """Snow down on the top of the column and wind across it, two
    combinations of them, and the weight of the column in Snow."""
    model = _buckling_model()
    snow = model.load_groups[0]
    snow.name = "Snow"
    snow.self_weight_coefficients = [0.0, 0.0, -1.0]
    wind = LoadGroup(id="lg2", name="Wind", is_load_case=True)
    wind.add_load(
        PointLoad(id="p2", magnitude=2.0, direction=[1, 0, 0], position=[0, 0, 2])
    )
    model.load_groups.append(wind)
    model.load_combinations = [
        LoadCombination(id="c1", name="ULS snow", load_groups={"lg1": 1.5, "lg2": 0.9}),
        LoadCombination(
            id="c2", name="ULS wind", load_groups={"lg1": 0.75, "lg2": 1.5}
        ),
    ]
    return model


class TestBucklingPerCombination:
    """A *BUCKLE step per combination, of its load cases times their factors."""

    def _steps(self, model, **selection):
        model.buckling_load_sets, _ = buckling_load_sets(model, **selection)
        buf = io.StringIO()
        write_analysis_steps(
            buf,
            model,
            analysis_type="linear_buckling",
            node_coords={1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 2.0)},
        )
        return buf.getvalue().split("*END STEP")[:-1]

    @staticmethod
    def _cloads(step):
        return {
            (int(node), int(dof)): float(value)
            for node, dof, value in re.findall(
                r"^(\d+), (\d), (\S+)$", step, flags=re.MULTILINE
            )
        }

    @staticmethod
    def _gravity(step):
        (value,) = re.findall(r"EALL, GRAV, (\S+),", step)
        return float(value)

    def test_a_step_per_combination(self):
        steps = self._steps(_two_cases())
        assert len(steps) == 2
        assert "** Buckling loads: ULS snow" in steps[0]
        assert "** Buckling loads: ULS wind" in steps[1]
        assert all(step.count("*BUCKLE") == 1 for step in steps)

    def test_loads_times_their_factors(self):
        first, second = (self._cloads(s) for s in self._steps(_two_cases()))
        assert first == {(2, 3): pytest.approx(-1.5), (2, 1): pytest.approx(1.8)}
        assert second == {(2, 3): pytest.approx(-0.75), (2, 1): pytest.approx(3.0)}

    def test_self_weight_times_its_factor(self):
        first, second = (self._gravity(s) for s in self._steps(_two_cases()))
        assert first == pytest.approx(1.5 * 9.81)
        assert second == pytest.approx(0.75 * 9.81)

    def test_load_cases_by_themselves(self):
        steps = self._steps(_two_cases(), load_cases=["Wind"])
        assert len(steps) == 1
        assert self._cloads(steps[0]) == {(2, 1): pytest.approx(2.0)}
        assert "GRAV" not in steps[0]

    def test_a_case_per_step_without_combinations(self):
        model = _two_cases()
        model.load_combinations = []
        steps = self._steps(model)
        assert [self._cloads(s) for s in steps] == [
            {(2, 3): pytest.approx(-1.0)},
            {(2, 1): pytest.approx(2.0)},
        ]
