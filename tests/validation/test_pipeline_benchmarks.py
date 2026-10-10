"""Validation tests: full pipeline (IFC in, results out) against closed-form answers.

Unlike the direct-CalculiX benchmarks next to this file, these go through
extraction, meshing, the input writer, the solver and the results export, so
they catch errors in section orientation, section properties, supports and
loads that a hand-written ``.inp`` cannot.

Models are the IfcOpenShell example files, edited in memory where a variant is
needed (rotating the member's ``Axis``, swapping the profile).

Reference values use Timoshenko beam theory (bending plus shear deflection):

* Cantilever under self-weight ``w = rho A g``:
  ``w L^4 / (8 E I) + w L^2 / (2 G A_s)``
* Fixed-fixed beam with central point load:
  ``P L^3 / (192 E I) + P L / (4 G A_s)``
"""

import json
import os
import shutil

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc  # noqa: E402

IFC_DIR = os.path.join("examples", "analysis-models", "ifcFiles")
CANTILEVER = os.path.join(IFC_DIR, "cantilever_01.ifc")
BEAM = os.path.join(IFC_DIR, "beam_01.ifc")

pytestmark = [
    pytest.mark.skipif(shutil.which("ccx") is None, reason="CalculiX not installed"),
    pytest.mark.skipif(
        not os.path.exists(CANTILEVER), reason="example models submodule missing"
    ),
]

G_ACCEL = 9.81
MESH_SIZE = 0.05  # m; 60 elements on the 3 m cantilever
DEFLECTION_TOLERANCE = 0.03

# cantilever_01.ifc: 3 m long, fully fixed at x = 0, 0.2 x 0.4 rectangle
# (profile XDim x YDim), Axis = +Z, so the 0.4 depth is vertical.
CANT_L = 3.0
CANT_E = 2.1e8
CANT_NU = 0.2
CANT_RHO = 7.8
CANT_G = CANT_E / (2 * (1 + CANT_NU))

# I-profile used for the open-section cases
I_B, I_H, I_TW, I_TF = 0.2, 0.4, 0.01, 0.02
I_AREA = 2 * I_B * I_TF + (I_H - 2 * I_TF) * I_TW
I_STRONG = (I_B * I_H**3 - (I_B - I_TW) * (I_H - 2 * I_TF) ** 3) / 12
I_WEAK = (2 * I_TF * I_B**3 + (I_H - 2 * I_TF) * I_TW**3) / 12


def _cantilever_self_weight(area: float, inertia: float, shear_area: float) -> float:
    """Tip deflection of the example cantilever under its own weight."""
    w = CANT_RHO * area * G_ACCEL
    bending = w * CANT_L**4 / (8 * CANT_E * inertia)
    shear = w * CANT_L**2 / (2 * CANT_G * shear_area)
    return bending + shear


def _cantilever_variant(tmp_path, axis=None, i_profile=False) -> str:
    """Write a copy of cantilever_01.ifc with a new Axis and/or an I profile."""
    model = ifcopenshell.open(CANTILEVER)
    if axis is not None:
        member = model.by_type("IfcStructuralCurveMember")[0]
        member.Axis.DirectionRatios = axis
    if i_profile:
        profile = model.create_entity(
            "IfcIShapeProfileDef",
            ProfileType="AREA",
            ProfileName="benchmark I",
            OverallWidth=I_B,
            OverallDepth=I_H,
            WebThickness=I_TW,
            FlangeThickness=I_TF,
        )
        model.by_type("IfcMaterialProfile")[0].Profile = profile
    path = str(tmp_path / "variant.ifc")
    model.write(path)
    return path


def _run(ifc_path: str, tmp_path, **kwargs) -> dict:
    """Run the pipeline and return the parsed results.json."""
    output_dir = str(tmp_path / "out")
    result = analyze_ifc(
        ifc_path=ifc_path, output_dir=output_dir, mesh_size=MESH_SIZE, **kwargs
    )
    assert result["status"] == "success", result.get("errors")
    with open(os.path.join(output_dir, "results.json")) as fh:
        return json.load(fh)


def _max_vertical_deflection(data: dict) -> float:
    return data["global_displacements"]["envelope"]["max_tz_m"]


class TestRectangularCantileverSelfWeight:
    """cantilever_01 under gravity, native B31 rectangular section."""

    AREA = 0.2 * 0.4
    SHEAR_AREA = AREA * 5 / 6

    def test_strong_axis_as_authored(self, tmp_path):
        """Axis = +Z puts the 0.4 m depth vertical: bending about the strong axis."""
        data = _run(CANTILEVER, tmp_path, gravity=True)
        expected = _cantilever_self_weight(
            self.AREA, 0.2 * 0.4**3 / 12, self.SHEAR_AREA
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )

    def test_weak_axis_when_section_is_rotated(self, tmp_path):
        """Axis = +Y lays the section on its side: bending about the weak axis."""
        path = _cantilever_variant(tmp_path, axis=(0.0, 1.0, 0.0))
        data = _run(path, tmp_path, gravity=True)
        expected = _cantilever_self_weight(
            self.AREA, 0.4 * 0.2**3 / 12, self.SHEAR_AREA
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )

    def test_reaction_balances_self_weight(self, tmp_path):
        """Vertical reaction equals the member's weight.

        CalculiX leaves out the share of the distributed load that lands on the
        restrained node itself (half an element), hence the 2% allowance.
        """
        data = _run(CANTILEVER, tmp_path, gravity=True)
        weight = CANT_RHO * self.AREA * G_ACCEL * CANT_L
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            weight, rel=0.02
        )


class TestISectionCantileverSelfWeight:
    """cantilever_01 with an I profile, analysed with U1 general sections."""

    def test_strong_axis(self, tmp_path):
        """Web vertical: bending about the strong axis, shear carried by the web."""
        path = _cantilever_variant(tmp_path, i_profile=True)
        data = _run(path, tmp_path, gravity=True)
        expected = _cantilever_self_weight(I_AREA, I_STRONG, I_H * I_TW)
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )

    def test_weak_axis(self, tmp_path):
        """Web horizontal: bending about the weak axis.

        CalculiX's general section takes a single shear factor, so the shear
        term uses the same web shear area the writer supplies.
        """
        path = _cantilever_variant(tmp_path, axis=(0.0, 1.0, 0.0), i_profile=True)
        data = _run(path, tmp_path, gravity=True)
        expected = _cantilever_self_weight(I_AREA, I_WEAK, I_H * I_TW)
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )


class TestFixedFixedBeamPointLoad:
    """beam_01: 4 m, both ends fully fixed, 20 kN at midspan, 0.3 m square."""

    LENGTH = 4.0
    LOAD = 20000.0
    E = 3.0e10
    NU = 0.2
    AREA = 0.3 * 0.3
    INERTIA = 0.3**4 / 12

    def test_midspan_deflection(self, tmp_path):
        data = _run(BEAM, tmp_path)
        shear_modulus = self.E / (2 * (1 + self.NU))
        expected = self.LOAD * self.LENGTH**3 / (
            192 * self.E * self.INERTIA
        ) + self.LOAD * self.LENGTH / (4 * shear_modulus * self.AREA * 5 / 6)
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )

    def test_reaction_equals_applied_load(self, tmp_path):
        data = _run(BEAM, tmp_path)
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            self.LOAD, rel=1e-3
        )


class TestCodeAsterReferences:
    """Self-weight results against the Code_Aster runs shipped with the models.

    ``examples/analysis-models/models/<name>/<name>.rmed`` holds IfcOpenShell's
    IFC2CA results for the same IFC files (Euler beams, DKT shells, gravity
    9.806 m/s2). The numbers below are the largest nodal translation in each
    file, read with h5py from ``CHA/Bld_DISP`` (six components per node,
    stored component by component).
    """

    STRUCTURE = os.path.join(IFC_DIR, "structure_01.ifc")

    def test_cantilever_01(self, tmp_path):
        """Reference 0.2766 mm; ours is slightly larger for shear deflection."""
        data = _run(CANTILEVER, tmp_path, gravity=True)
        assert _max_vertical_deflection(data) == pytest.approx(2.766e-4, rel=0.03)

    def test_structure_01(self, tmp_path):
        """Slab on a wall and two columns. Reference 0.4273 mm.

        The tolerance is wide because the slab-to-wall edge hinge is not
        modelled and linear shell elements converge slowly. Before surface
        materials, joints and supports were read correctly this model gave
        between 1.7 and 17 mm.
        """
        output_dir = str(tmp_path / "out")
        result = analyze_ifc(
            ifc_path=self.STRUCTURE, output_dir=output_dir, mesh_size=0.5, gravity=True
        )
        assert result["status"] == "success", result.get("errors")
        with open(os.path.join(output_dir, "results.json")) as fh:
            data = json.load(fh)
        max_disp = data["global_displacements"]["envelope"]["max_displacement_m"]
        assert max_disp == pytest.approx(4.273e-4, rel=0.25)

    def test_structure_01_supports_and_joints(self, tmp_path):
        """The wall base is a line support; the slab-to-wall joint is no support."""
        output_dir = str(tmp_path / "out")
        analyze_ifc(
            ifc_path=self.STRUCTURE, output_dir=output_dir, mesh_size=0.5, gravity=True
        )
        with open(os.path.join(output_dir, "analysis.inp")) as fh:
            text = fh.read()
        support_sets = {}
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("*NSET, NSET=BC_"):
                name = line.split("NSET=")[-1].strip()
                nodes = []
                for data_line in lines[i + 1 :]:
                    if data_line.startswith("*"):
                        break
                    nodes += [n for n in data_line.split(",") if n.strip()]
                support_sets[name] = len(nodes)
        # Wall base edge plus two column bases; the slab-wall joint has no
        # AppliedCondition and must not appear.
        assert len(support_sets) == 3
        assert sorted(support_sets.values())[:2] == [1, 1]
        assert max(support_sets.values()) > 2
        # Weight: 6 m3 of slab and 2.4 m3 of wall at 7.8 kg/m3, plus columns
        with open(os.path.join(output_dir, "results.json")) as fh:
            reaction = json.load(fh)["global_reactions"]["total"]["fz_N"]
        assert 600 < reaction < 700
