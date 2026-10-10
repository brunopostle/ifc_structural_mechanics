"""Open sections analysed as a rectangle of the same stiffness."""

import io
import re

import pytest

from ifc_structural_mechanics.config.analysis_config import AnalysisConfig
from ifc_structural_mechanics.converters.section_profiles import equivalent_rectangle
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.result import DisplacementResult, StressResult
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)
from ifc_structural_mechanics.utils.error_handling import MeshingError

E, NU, RHO = 210e9, 0.3, 7850.0
B, H, TW, TF = 0.2, 0.4, 0.01, 0.02
AREA = 2 * B * TF + (H - 2 * TF) * TW
I_STRONG = (B * H**3 - (B - TW) * (H - 2 * TF) ** 3) / 12
I_WEAK = (2 * TF * B**3 + (H - 2 * TF) * TW**3) / 12


def _material():
    return Material(
        id="steel", name="Steel", density=RHO, elastic_modulus=E, poisson_ratio=NU
    )


def _i_beam(member_id, start, end):
    section = Section(
        id=f"sec_{member_id}",
        name="I 200x400",
        section_type="i",
        area=AREA,
        dimensions={
            "width": B,
            "height": H,
            "web_thickness": TW,
            "flange_thickness": TF,
        },
    )
    section.moment_of_inertia_y = I_STRONG
    section.moment_of_inertia_z = I_WEAK
    return CurveMember(
        id=member_id, geometry=[start, end], material=_material(), section=section
    )


def _rect_beam(member_id, start, end):
    return CurveMember(
        id=member_id,
        geometry=[start, end],
        material=_material(),
        section=Section.create_rectangular_section(
            id=f"sec_{member_id}", name="rect", width=0.2, height=0.3
        ),
    )


def _writer(with_native_beam=True, open_sections="equivalent"):
    """An I-section beam, and optionally a rectangular column under its end."""
    model = StructuralModel(id="model")
    model.add_member(_i_beam("beam", (0, 0, 3), (4, 0, 3)))
    if with_native_beam:
        model.add_member(_rect_beam("column", (4, 0, 0), (4, 0, 3)))
    config = AnalysisConfig()
    config.set_open_sections(open_sections)
    writer = UnifiedCalculixWriter(domain_model=model, analysis_config=config)
    writer.nodes = {
        1: (0.0, 0.0, 3.0),
        2: (2.0, 0.0, 3.0),
        3: (4.0, 0.0, 3.0),
        4: (4.0, 0.0, 0.0),
    }
    writer.elements = {1: {"type": "B32R", "nodes": [1, 2, 3]}}
    writer.short_id_map = {"beam": "M1", "column": "M2"}
    writer.element_sets = {"MEMBER_M1": [1]}
    if with_native_beam:
        writer.elements[2] = {"type": "B31", "nodes": [4, 3]}
        writer.element_sets["MEMBER_M2"] = [2]
    writer._identify_and_retype_u1_members()
    return writer


class TestEquivalentRectangle:
    def test_matches_area_and_both_inertias(self):
        a, b, factor = equivalent_rectangle(AREA, I_STRONG, I_WEAK)

        assert factor * a * b == pytest.approx(AREA)
        assert factor * b * a**3 / 12 == pytest.approx(I_STRONG)
        assert factor * a * b**3 / 12 == pytest.approx(I_WEAK)

    def test_first_dimension_goes_with_the_first_inertia(self):
        a, b, _ = equivalent_rectangle(AREA, I_STRONG, I_WEAK)

        assert a > b

    def test_a_rectangle_is_its_own_equivalent(self):
        a, b, factor = equivalent_rectangle(0.08, 0.2 * 0.4**3 / 12, 0.4 * 0.2**3 / 12)

        assert (a, b, factor) == pytest.approx((0.4, 0.2, 1.0))

    def test_missing_property_is_an_error(self):
        with pytest.raises(ValueError, match="positive area and inertias"):
            equivalent_rectangle(AREA, I_STRONG, 0.0)


class TestChoiceOfModel:
    def test_mixed_model_gets_equivalent_rectangles(self):
        writer = _writer()

        assert writer._u1_members == set()
        assert set(writer._equivalent_sections) == {"beam"}
        assert writer.elements[1]["type"] == "B32R"

    def test_model_of_open_sections_only_gets_them_too(self):
        writer = _writer(with_native_beam=False)

        assert writer._u1_members == set()
        assert set(writer._equivalent_sections) == {"beam"}

    def test_user_elements_can_be_asked_for(self):
        writer = _writer(open_sections="user_element")

        assert writer._u1_members == {"beam"}
        assert writer._equivalent_sections == {}

    def test_user_is_told_and_the_model_remembers(self):
        writer = _writer()

        messages = [w["message"] for w in writer.domain_model.analysis_warnings]
        assert len(messages) == 1
        assert "1 member(s) whose section is not a solid rectangle" in messages[0]
        assert "no stress is reported" in messages[0]
        assert writer.domain_model.equivalent_section_members == {"beam"}

    @pytest.mark.parametrize(
        "section",
        [
            Section.create_circular_section("s", "bar", radius=0.1),
            Section.create_hollow_circular_section(
                "s", "pipe", outer_radius=0.1, thickness=0.01
            ),
            Section.create_hollow_rectangular_section(
                "s", "box", outer_width=0.2, outer_height=0.4, thickness=0.01
            ),
        ],
        ids=["circular", "pipe", "box"],
    )
    def test_round_and_hollow_sections_get_one_too(self, section):
        """CalculiX's own CIRC, PIPE and BOX sections are not used."""
        writer = _writer()
        beam = writer.domain_model.get_member("beam")
        beam.section = section
        writer._equivalent_sections = {}
        writer._identify_and_retype_u1_members()

        a, b, factor = writer._equivalent_sections["beam"]
        assert factor * a * b == pytest.approx(section.area)
        assert factor * b * a**3 / 12 == pytest.approx(section.moment_of_inertia_y)
        assert factor * a * b**3 / 12 == pytest.approx(section.moment_of_inertia_z)

    def test_section_without_inertia_is_an_error(self):
        model = StructuralModel(id="model")
        beam = _i_beam("beam", (0, 0, 3), (4, 0, 3))
        beam.section.moment_of_inertia_z = 0.0
        model.add_member(beam)
        writer = UnifiedCalculixWriter(domain_model=model)
        writer.elements = {1: {"type": "B31", "nodes": [1, 2]}}
        writer.short_id_map = {"beam": "M1"}
        writer.element_sets = {"MEMBER_M1": [1]}

        with pytest.raises(MeshingError, match="cannot be analysed"):
            writer._identify_and_retype_u1_members()

    def test_unknown_choice_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid open section model"):
            AnalysisConfig().set_open_sections("solid")


def _block(text, header):
    """Data lines following the first keyword line that contains ``header``."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if header in line)
    return lines[start + 1 :]


class TestWrittenInput:
    def test_material_is_scaled_to_the_real_section(self):
        writer = _writer()
        out = io.StringIO()
        writer._write_materials(out)
        text = out.getvalue()

        a, b, factor = writer._equivalent_sections["beam"]
        lines = _block(text, "NAME=MAT_EQ_M1")
        assert lines[0] == "*ELASTIC, TYPE=ENGINEERING CONSTANTS"
        constants = [float(v) for v in lines[1].rstrip(",").split(",")]
        modulus, poisson = constants[0], constants[3]
        density = float(lines[4])
        assert constants[:3] == pytest.approx([modulus] * 3)
        assert constants[3:6] == pytest.approx([NU] * 3)
        assert modulus * a * b == pytest.approx(E * AREA, rel=1e-6)
        assert modulus * b * a**3 / 12 == pytest.approx(E * I_STRONG, rel=1e-6)
        assert modulus * a * b**3 / 12 == pytest.approx(E * I_WEAK, rel=1e-6)
        assert density * a * b == pytest.approx(RHO * AREA, rel=1e-6)
        assert poisson == pytest.approx(NU)

    def test_shear_moduli_give_the_section_its_own_shear_stiffness(self):
        """CalculiX's expanded rectangle shears over its whole area."""
        writer = _writer()
        section = writer.domain_model.get_member("beam").section
        section.shear_area_y = H * TW
        section.shear_area_z = 2 * B * TF
        out = io.StringIO()
        writer._write_materials(out)

        a, b, _ = writer._equivalent_sections["beam"]
        lines = _block(out.getvalue(), "NAME=MAT_EQ_M1")
        constants = [float(v) for v in lines[1].rstrip(",").split(",")]
        shear = E / (2 * (1 + NU))
        assert constants[6] * a * b == pytest.approx(shear * H * TW, rel=1e-6)
        assert constants[7] * a * b == pytest.approx(shear * 2 * B * TF, rel=1e-6)
        # In the plane of the cross-section the scaled material is as isotropic
        assert float(lines[2]) == pytest.approx(constants[0] / (2 * (1 + NU)))

    def test_without_shear_areas_the_material_is_isotropic(self):
        writer = _writer()
        section = writer.domain_model.get_member("beam").section
        section.shear_area_y = section.shear_area_z = None
        out = io.StringIO()
        writer._write_materials(out)

        lines = _block(out.getvalue(), "NAME=MAT_EQ_M1")
        constants = [float(v) for v in lines[1].rstrip(",").split(",")]
        assert constants[6:8] == pytest.approx([float(lines[2])] * 2)

    def test_shared_material_is_left_alone(self):
        writer = _writer()
        out = io.StringIO()
        writer._write_materials(out)

        modulus = float(_block(out.getvalue(), "NAME=MAT_steel")[1].split(",")[0])
        assert modulus == pytest.approx(E)

    def test_section_is_a_rectangle_with_depth_first(self):
        writer = _writer()
        out = io.StringIO()
        writer._write_beam_section_for_set(
            out,
            writer.domain_model.get_member("beam"),
            "MEMBER_M1",
            "steel",
            (0, 0, 1),
            elem_ids=[1],
        )
        lines = out.getvalue().splitlines()

        assert lines[0] == "*ORIENTATION, NAME=OR_MEMBER_M1, SYSTEM=RECTANGULAR"
        # Material 1 axis along the member (global X), 2 axis along the depth
        assert [float(v) for v in lines[1].split(",")] == pytest.approx(
            [1, 0, 0, 0, 0, 1]
        )
        assert re.search(
            r"MATERIAL=MAT_EQ_M1, SECTION=RECT, ORIENTATION=OR_MEMBER_M1$", lines[2]
        )
        a, b, _ = writer._equivalent_sections["beam"]
        assert [float(v) for v in lines[3].split(",")] == pytest.approx([a, b])
        assert [float(v) for v in lines[4].split(",")] == pytest.approx([0, 0, 1])

    def test_native_section_keeps_the_shared_material(self):
        writer = _writer()
        out = io.StringIO()
        writer._write_beam_section_for_set(
            out,
            writer.domain_model.get_member("column"),
            "MEMBER_M2",
            "steel",
            (1, 0, 0),
        )

        assert "MATERIAL=MAT_steel, SECTION=RECT" in out.getvalue()


class TestResults:
    def _members(self):
        writer = _writer()
        model = writer.domain_model
        model.set_analysis_elements("beam", [1])
        model.set_analysis_elements("column", [2])
        parsed = {"displacement": [], "stress": []}
        for node in (11, 21):
            displacement = DisplacementResult(reference_element=node)
            displacement.set_translations([0.0, 0.0, 0.002])
            displacement.add_metadata("load_case", "Dead")
            parsed["displacement"].append(displacement)
            stress = StressResult(reference_element=node)
            for name in ("sxx", "syy", "szz", "sxy", "syz", "sxz"):
                stress.add_value(name, 1e6 if name == "sxx" else 0.0)
            stress.add_metadata("load_case", "Dead")
            parsed["stress"].append(stress)
        exporter = ResultsExporter(model, parsed, element_nodes={1: [11], 2: [21]})
        return {m["id"]: m for m in exporter._build()["members"]}

    def test_equivalent_member_reports_displacement_but_no_stress(self):
        beam = self._members()["beam"]

        assert beam["section_model"] == "equivalent_rectangle"
        assert beam["by_load_case"]["Dead"] == {"max_displacement_m": 0.002}

    def test_native_member_is_unchanged(self):
        column = self._members()["column"]

        assert "section_model" not in column
        assert column["by_load_case"]["Dead"]["max_von_mises_Pa"] == 1e6
