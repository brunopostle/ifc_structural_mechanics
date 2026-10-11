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
* Slab carried by two cantilever beams lying in it: the cantilever formula
  with each beam taking its own weight and half the slab's, and half the
  slab's bending stiffness
* Simply supported rectangular plate under uniform load: Navier's double
  sine series, plus the Mindlin shear term ``M / (kappa G t)`` where ``M`` is
  the moment sum
"""

import json
import math
import os
import shutil

import numpy as np
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.analysis.results_parser import (  # noqa: E402
    ResultsParser,
)
from ifc_structural_mechanics.api.structural_analysis import analyze_ifc  # noqa: E402
from ifc_structural_mechanics.converters.section_profiles import (  # noqa: E402
    expanded_rectangle_torsion_stiffness,
)
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    ModelExtractionError,
)

IFC_DIR = os.path.join("examples", "analysis-models", "ifcFiles")
CANTILEVER = os.path.join(IFC_DIR, "cantilever_01.ifc")
BEAM = os.path.join(IFC_DIR, "beam_01.ifc")
SLAB = os.path.join(IFC_DIR, "slab_01.ifc")

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

# Slab carried by two beams lying in it (built from scratch, same material)
SOB_L, SOB_B, SOB_T = 5.0, 1.0, 0.1
SOB_BEAM_B, SOB_BEAM_H = 0.2, 0.4

# Columns under slab_01 that the file does not connect to it
COLUMN_SIDE, COLUMN_HEIGHT = 0.3, 3.0
COLUMN_POSITIONS = ((1.25, 0.75), (3.75, 0.75), (1.25, 2.25), (3.75, 2.25))

# Cantilever with an arm on its tip, to twist it (built from scratch)
TORSION_E, TORSION_NU = 2.1e11, 0.3
TORSION_LA, TORSION_LB, TORSION_P = 3.0, 1.0, 1000.0

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


def _edge_condition(model, fixed):
    """An IfcBoundaryEdgeCondition from six booleans (dx, dy, dz, drx, dry, drz)."""
    return model.create_entity(
        "IfcBoundaryEdgeCondition",
        None,
        *[model.create_entity("IfcBoolean", bool(value)) for value in fixed],
    )


def _add_area_load(model, slab, force_per_area) -> None:
    """Put a uniform area load in global axes on a slab, in a load case of its own."""
    history = slab.OwnerHistory
    action = model.create_entity(
        "IfcStructuralPlanarAction",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=history,
        Name="benchmark area load",
        ObjectPlacement=slab.ObjectPlacement,
        AppliedLoad=model.create_entity(
            "IfcStructuralLoadPlanarForce",
            None,
            *[float(component) for component in force_per_area],
        ),
        GlobalOrLocal="GLOBAL_COORDS",
        ProjectedOrTrue="TRUE_LENGTH",
        PredefinedType="CONST",
    )
    model.create_entity(
        "IfcRelConnectsStructuralActivity",
        ifcopenshell.guid.new(),
        history,
        None,
        None,
        slab,
        action,
    )
    case = model.create_entity(
        "IfcStructuralLoadCase",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=history,
        Name="Imposed",
        PredefinedType="LOAD_CASE",
        ActionType="VARIABLE_Q",
        ActionSource="LIVE_LOAD_Q",
    )
    model.create_entity(
        "IfcRelAssignsToGroup",
        ifcopenshell.guid.new(),
        history,
        None,
        None,
        [action],
        None,
        case,
    )
    analysis = model.by_type("IfcStructuralAnalysisModel")[0]
    analysis.LoadedBy = list(analysis.LoadedBy or []) + [case]


def _slab_variant(tmp_path, edge_conditions, extra_edges=(), area_load=None) -> str:
    """Write a copy of slab_01.ifc with new line supports.

    slab_01 is a 5 m x 3 m slab, 0.2 m thick, with line supports along x = 0
    and x = 5. ``edge_conditions`` gives the support condition of those two, in
    that order. ``extra_edges`` adds line supports, each as (start, end, fixed).
    The conditions on the member side of each connection are removed, so the
    support condition alone decides how the edge behaves. ``area_load`` adds a
    uniform load on the slab (force per area, global axes) in a load case.
    """
    model = ifcopenshell.open(SLAB)
    slab = model.by_type("IfcStructuralSurfaceMember")[0]
    existing = sorted(
        model.by_type("IfcStructuralCurveConnection"), key=lambda c: c.id()
    )
    for connection, fixed in zip(existing, edge_conditions):
        connection.AppliedCondition = _edge_condition(model, fixed)
    for relation in model.by_type("IfcRelConnectsStructuralMember"):
        relation.AppliedCondition = None

    template = existing[0]
    context = template.Representation.Representations[0].ContextOfItems
    group = model.by_type("IfcRelAssignsToGroup")[0]
    for start, end, fixed in extra_edges:
        vertices = [
            model.create_entity(
                "IfcVertexPoint", model.create_entity("IfcCartesianPoint", point)
            )
            for point in (start, end)
        ]
        edge = model.create_entity("IfcEdge", vertices[0], vertices[1])
        shape = model.create_entity(
            "IfcProductDefinitionShape",
            None,
            None,
            [
                model.create_entity(
                    "IfcTopologyRepresentation", context, "Reference", "Edge", [edge]
                )
            ],
        )
        connection = model.create_entity(
            "IfcStructuralCurveConnection",
            ifcopenshell.guid.new(),
            template.OwnerHistory,
            "benchmark edge",
            None,
            None,
            template.ObjectPlacement,
            shape,
            _edge_condition(model, fixed),
            model.create_entity("IfcDirection", (0.0, 0.0, 1.0)),
        )
        model.create_entity(
            "IfcRelConnectsStructuralMember",
            ifcopenshell.guid.new(),
            template.OwnerHistory,
            None,
            None,
            slab,
            connection,
        )
        group.RelatedObjects = list(group.RelatedObjects) + [connection]
    if area_load is not None:
        _add_area_load(model, slab, area_load)
    path = str(tmp_path / "variant.ifc")
    model.write(path)
    return path


def _run(ifc_path: str, tmp_path, mesh_size: float = MESH_SIZE, **kwargs) -> dict:
    """Run the pipeline and return the parsed results.json."""
    output_dir = str(tmp_path / f"out_{mesh_size}")
    result = analyze_ifc(
        ifc_path=ifc_path, output_dir=output_dir, mesh_size=mesh_size, **kwargs
    )
    assert result["status"] == "success", result.get("errors")
    with open(os.path.join(output_dir, "results.json")) as fh:
        return json.load(fh)


def _max_vertical_deflection(data: dict) -> float:
    return data["global_displacements"]["envelope"]["max_tz_m"]


FORCE_TOLERANCE = 0.01


def _curve_member_envelope(data: dict) -> dict:
    """The envelope of the model's only curve member."""
    (member,) = [m for m in data["members"] if m["type"] == "curve"]
    return member["envelope"]


def _curve_member_diagram(data: dict) -> dict:
    """The section force diagram of the model's only curve member and load case."""
    (member,) = [m for m in data["members"] if m["type"] == "curve"]
    (diagram,) = member["section_force_diagrams"].values()
    return diagram


class TestRectangularCantileverSelfWeight:
    """cantilever_01 under gravity, native rectangular section (B32R)."""

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

    def test_section_forces_at_the_root(self, tmp_path):
        """Shear w L, moment w L^2 / 2 and the bending stress that goes with it."""
        data = _run(CANTILEVER, tmp_path, gravity=True)
        envelope = _curve_member_envelope(data)
        load = CANT_RHO * G_ACCEL * 0.2 * 0.4
        moment = load * CANT_L**2 / 2
        forces = envelope["section_forces"]
        assert forces["max_Vf1_N"] == pytest.approx(load * CANT_L, rel=FORCE_TOLERANCE)
        assert forces["max_Mf1_Nm"] == pytest.approx(moment, rel=FORCE_TOLERANCE)
        assert forces["max_Mf2_Nm"] < 1e-3 * moment
        assert forces["max_N_N"] < 1e-3 * load * CANT_L
        assert envelope["max_normal_stress_Pa"] == pytest.approx(
            moment / (0.2 * 0.4**3 / 12) * 0.2, rel=FORCE_TOLERANCE
        )

    def test_force_diagrams_along_the_member(self, tmp_path):
        """V = -w (L - x) and M = w (L - x)^2 / 2, with their signs.

        The member runs from the support along +X and its section's 1
        direction is up. The part beyond a cross-section pulls the part before
        it down (negative shear along 1) and puts the top in tension
        (positive moment).
        """
        data = _run(CANTILEVER, tmp_path, gravity=True)
        (member,) = data["members"]
        assert member["section_axes"]["x"] == pytest.approx([1.0, 0.0, 0.0])
        assert member["section_axes"]["1"] == pytest.approx([0.0, 0.0, 1.0])
        diagram = _curve_member_diagram(data)
        load = CANT_RHO * G_ACCEL * 0.2 * 0.4
        root_shear, root_moment = load * CANT_L, load * CANT_L**2 / 2
        assert diagram["distance_m"][0] == pytest.approx(0.0, abs=1e-9)
        assert diagram["distance_m"][-1] == pytest.approx(CANT_L)
        assert len(diagram["distance_m"]) == 121  # 60 quadratic elements
        for x, shear, moment in zip(
            diagram["distance_m"], diagram["Vf1_N"], diagram["Mf1_Nm"]
        ):
            assert shear == pytest.approx(
                -load * (CANT_L - x), abs=FORCE_TOLERANCE * root_shear
            )
            assert moment == pytest.approx(
                load * (CANT_L - x) ** 2 / 2, abs=FORCE_TOLERANCE * root_moment
            )

    def test_weak_axis_forces_are_reported_about_the_other_axis(self, tmp_path):
        path = _cantilever_variant(tmp_path, axis=(0.0, 1.0, 0.0))
        data = _run(path, tmp_path, gravity=True)
        forces = _curve_member_envelope(data)["section_forces"]
        load = CANT_RHO * G_ACCEL * 0.2 * 0.4
        assert forces["max_Vf2_N"] == pytest.approx(load * CANT_L, rel=FORCE_TOLERANCE)
        assert forces["max_Mf2_Nm"] == pytest.approx(
            load * CANT_L**2 / 2, rel=FORCE_TOLERANCE
        )
        assert forces["max_Mf1_Nm"] < 1e-3 * forces["max_Mf2_Nm"]

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


class TestImplausibleResults:
    """A model that solves with absurd displacements says so.

    cantilever_01 with its elastic modulus divided by 100 000: the same
    statics, and a tip that drops 28 m on a 3 m member.
    """

    def _soft_cantilever(self, tmp_path) -> str:
        model = ifcopenshell.open(CANTILEVER)
        for prop in model.by_type("IfcPropertySingleValue"):
            if prop.Name == "YoungModulus":
                prop.NominalValue = model.create_entity(
                    "IfcModulusOfElasticityMeasure", CANT_E / 1e5
                )
        path = str(tmp_path / "soft.ifc")
        model.write(path)
        return path

    def _warnings(self, ifc_path, tmp_path):
        result = analyze_ifc(
            ifc_path=ifc_path,
            output_dir=str(tmp_path / "out"),
            mesh_size=0.25,
            gravity=True,
        )
        assert result["status"] == "success", result.get("errors")
        return [w["message"] for w in result["warnings"]]

    def test_soft_cantilever_is_reported_twice_over(self, tmp_path):
        messages = self._warnings(self._soft_cantilever(tmp_path), tmp_path)
        mechanism = [m for m in messages if "probably a mechanism" in m]
        distorted = [m for m in messages if "distorts by" in m]
        assert len(mechanism) == 1 and len(distorted) == 1
        assert mechanism[0].startswith("Load case Gravity: the largest displacement")
        assert "in a model 3 m across" in mechanism[0]
        assert "over its 3 m" in distorted[0]

    def test_the_real_cantilever_is_not(self, tmp_path):
        messages = self._warnings(CANTILEVER, tmp_path)
        assert not any("mechanism" in m or "distorts by" in m for m in messages)


class TestISectionCantileverSelfWeight:
    """cantilever_01 with an I profile, analysed with U1 general sections.

    U1 is no longer the default; it is kept for comparison and for models
    where torsion of an open section matters.
    """

    U1 = {"gravity": True, "open_sections": "user_element"}

    def test_strong_axis(self, tmp_path):
        """Web vertical: bending about the strong axis, shear carried by the web."""
        path = _cantilever_variant(tmp_path, i_profile=True)
        data = _run(path, tmp_path, **self.U1)
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
        data = _run(path, tmp_path, **self.U1)
        expected = _cantilever_self_weight(I_AREA, I_WEAK, I_H * I_TW)
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )


class TestISectionAsEquivalentRectangle:
    """The same I-section cantilever on a native beam element.

    This is what every section other than a solid rectangle gets by default:
    a rectangle with the section's EA, EI about both axes, shear stiffness
    and weight, on an element stock CalculiX can mix with any other.
    """

    def test_strong_axis(self, tmp_path):
        path = _cantilever_variant(tmp_path, i_profile=True)
        data = _run(path, tmp_path, gravity=True)
        expected = _cantilever_self_weight(I_AREA, I_STRONG, I_H * I_TW)
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )

    def test_weak_axis(self, tmp_path):
        path = _cantilever_variant(tmp_path, axis=(0.0, 1.0, 0.0), i_profile=True)
        data = _run(path, tmp_path, gravity=True)
        expected = _cantilever_self_weight(I_AREA, I_WEAK, 2 * I_B * I_TF)
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )

    def test_reaction_is_the_weight_of_the_real_section(self, tmp_path):
        path = _cantilever_variant(tmp_path, i_profile=True)
        data = _run(path, tmp_path, gravity=True)
        weight = CANT_RHO * G_ACCEL * I_AREA * CANT_L
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            weight, rel=0.02
        )

    def test_solver_stress_is_not_reported(self, tmp_path):
        """The stresses in the result file are the rectangle's, not the section's."""
        path = _cantilever_variant(tmp_path, i_profile=True)
        data = _run(path, tmp_path, gravity=True)
        (member,) = data["members"]
        assert member["section_model"] == "equivalent_rectangle"
        assert "max_von_mises_Pa" not in member["envelope"]
        assert member["envelope"]["max_displacement_m"] > 0

    @pytest.mark.parametrize(
        "axis, inertia, fibre, moment_key",
        [
            (None, I_STRONG, I_H / 2, "max_Mf1_Nm"),
            ((0.0, 1.0, 0.0), I_WEAK, I_B / 2, "max_Mf2_Nm"),
        ],
        ids=["strong axis", "weak axis"],
    )
    def test_stress_comes_from_the_forces_and_the_real_section(
        self, tmp_path, axis, inertia, fibre, moment_key
    ):
        """The rectangle's stresses are not the section's; its resultants are."""
        path = _cantilever_variant(tmp_path, axis=axis, i_profile=True)
        data = _run(path, tmp_path, gravity=True)
        envelope = _curve_member_envelope(data)
        load = CANT_RHO * G_ACCEL * I_AREA
        moment = load * CANT_L**2 / 2
        assert envelope["section_forces"][moment_key] == pytest.approx(
            moment, rel=FORCE_TOLERANCE
        )
        assert envelope["max_normal_stress_Pa"] == pytest.approx(
            moment / inertia * fibre, rel=FORCE_TOLERANCE
        )


class TestMaterialWithoutDensity:
    """cantilever_01 with the density taken out of its material.

    The member used to be given the weight of steel. Now it weighs nothing,
    the result says so, and asking for self-weight is refused.
    """

    def _variant(self, tmp_path) -> str:
        model = ifcopenshell.open(CANTILEVER)
        for pset in model.by_type("IfcMaterialProperties"):
            if pset.Name == "Pset_MaterialCommon":
                model.remove(pset)
        path = str(tmp_path / "variant.ifc")
        model.write(path)
        return path

    def test_warning_reaches_the_result(self, tmp_path):
        result = analyze_ifc(
            ifc_path=self._variant(tmp_path),
            output_dir=str(tmp_path / "out"),
            mesh_size=MESH_SIZE,
        )
        assert result["status"] == "success", result.get("errors")
        messages = [w["message"] for w in result["warnings"]]
        assert any("no mass density" in m and "weightless" in m for m in messages)

    def test_self_weight_is_refused(self, tmp_path):
        with pytest.raises(ModelExtractionError, match="no mass density"):
            analyze_ifc(
                ifc_path=self._variant(tmp_path),
                output_dir=str(tmp_path / "out"),
                mesh_size=MESH_SIZE,
                gravity=True,
            )


class TestRoundAndHollowSections:
    """cantilever_01 with a bar, a tube and a box, as equivalent rectangles.

    CalculiX has CIRC, PIPE and BOX sections of its own. They are not used:
    a PIPE cantilever came out 83 % too flexible and as heavy as a solid bar,
    and B31 rejects PIPE altogether. Before that could be seen, hollow
    profiles were being read as solid ones and a solid circle as a default
    0.1 x 0.2 rectangle. The reaction shows which section was analysed.
    """

    RADIUS, WALL = 0.15, 0.01
    WIDTH, DEPTH = 0.2, 0.4

    def _check(self, tmp_path, ifc_class, attributes, area, inertia, shear_area):
        model = ifcopenshell.open(CANTILEVER)
        model.by_type("IfcMaterialProfile")[0].Profile = model.create_entity(
            ifc_class, ProfileType="AREA", ProfileName="benchmark", **attributes
        )
        path = str(tmp_path / "variant.ifc")
        model.write(path)
        data = _run(path, tmp_path, gravity=True)
        assert _max_vertical_deflection(data) == pytest.approx(
            _cantilever_self_weight(area, inertia, shear_area),
            rel=DEFLECTION_TOLERANCE,
        )
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            CANT_RHO * G_ACCEL * area * CANT_L, rel=0.02
        )

    def test_solid_circle(self, tmp_path):
        area = math.pi * self.RADIUS**2
        self._check(
            tmp_path,
            "IfcCircleProfileDef",
            {"Radius": self.RADIUS},
            area,
            math.pi / 4 * self.RADIUS**4,
            0.9 * area,
        )

    def test_tube(self, tmp_path):
        inner = self.RADIUS - self.WALL
        area = math.pi * (self.RADIUS**2 - inner**2)
        ratio = (inner / self.RADIUS) ** 2
        cowper = 7.8 * (1 + ratio) ** 2 / (8.8 * (1 + ratio) ** 2 + 23.6 * ratio)
        self._check(
            tmp_path,
            "IfcCircleHollowProfileDef",
            {"Radius": self.RADIUS, "WallThickness": self.WALL},
            area,
            math.pi / 4 * (self.RADIUS**4 - inner**4),
            cowper * area,
        )

    def test_box(self, tmp_path):
        inner_w, inner_d = self.WIDTH - 2 * self.WALL, self.DEPTH - 2 * self.WALL
        self._check(
            tmp_path,
            "IfcRectangleHollowProfileDef",
            {"XDim": self.WIDTH, "YDim": self.DEPTH, "WallThickness": self.WALL},
            self.WIDTH * self.DEPTH - inner_w * inner_d,
            (self.WIDTH * self.DEPTH**3 - inner_w * inner_d**3) / 12,
            2 * self.DEPTH * self.WALL,
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

    def test_section_forces(self, tmp_path):
        """Shear P / 2 throughout; moment P L / 8 at the ends and at midspan."""
        data = _run(BEAM, tmp_path)
        forces = _curve_member_envelope(data)["section_forces"]
        assert forces["max_Vf1_N"] == pytest.approx(self.LOAD / 2, rel=FORCE_TOLERANCE)
        assert forces["max_Mf1_Nm"] == pytest.approx(
            self.LOAD * self.LENGTH / 8, rel=FORCE_TOLERANCE
        )

    def test_shear_steps_under_the_load(self, tmp_path):
        """-P/2 before midspan and +P/2 after it, both listed at midspan.

        The solver's stress at the loaded cross-section is the average of the
        two sides, which would make the shear zero there.
        """
        data = _run(BEAM, tmp_path, mesh_size=0.25)
        diagram = _curve_member_diagram(data)
        half = self.LOAD / 2
        at_load = [
            i
            for i, x in enumerate(diagram["distance_m"])
            if x == pytest.approx(self.LENGTH / 2)
        ]
        assert [diagram["Vf1_N"][i] for i in at_load] == pytest.approx(
            [-half, half], rel=FORCE_TOLERANCE
        )
        for x, shear in zip(diagram["distance_m"], diagram["Vf1_N"]):
            sign = -1 if x < self.LENGTH / 2 else 1
            if x != pytest.approx(self.LENGTH / 2):
                assert shear == pytest.approx(sign * half, rel=FORCE_TOLERANCE)
        # Hogging at the supports, sagging under the load
        moment = self.LOAD * self.LENGTH / 8
        assert diagram["Mf1_Nm"][0] == pytest.approx(moment, rel=FORCE_TOLERANCE)
        assert diagram["Mf1_Nm"][at_load[0]] == pytest.approx(
            -moment, rel=FORCE_TOLERANCE
        )
        assert diagram["Mf1_Nm"][-1] == pytest.approx(moment, rel=FORCE_TOLERANCE)

    def test_reaction_equals_applied_load(self, tmp_path):
        data = _run(BEAM, tmp_path)
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            self.LOAD, rel=1e-3
        )


def _give_beam_01_an_i_profile(model) -> None:
    """Swap beam_01's 300 mm square for the 200 x 400 I section, in millimetres."""
    old = model.by_type("IfcRectangleProfileDef")[0]
    new = model.create_entity(
        "IfcIShapeProfileDef",
        ProfileType="AREA",
        ProfileName="benchmark I",
        OverallWidth=I_B * 1000,
        OverallDepth=I_H * 1000,
        WebThickness=I_TW * 1000,
        FlangeThickness=I_TF * 1000,
    )
    for user in model.get_inverse(old):
        for name, value in user.get_info(recursive=False).items():
            if value == old:
                setattr(user, name, new)


def _beam_with_line_load(tmp_path, force_per_metre, i_profile=False) -> str:
    """Write beam_01.ifc with its point load replaced by a uniform line load.

    ``force_per_metre`` is the load in global axes, in N/m. beam_01 is in
    millimetres and newtons, so it is written in N/mm. With ``i_profile`` the
    section becomes the 200 x 400 I.
    """
    model = ifcopenshell.open(BEAM)
    if i_profile:
        _give_beam_01_an_i_profile(model)
    member = model.by_type("IfcStructuralCurveMember")[0]
    point_action = model.by_type("IfcStructuralPointAction")[0]
    action = model.create_entity(
        "IfcStructuralLinearAction",
        ifcopenshell.guid.new(),
        point_action.OwnerHistory,
        "benchmark line load",
        None,
        None,
        member.ObjectPlacement,
        member.Representation,
        model.create_entity(
            "IfcStructuralLoadLinearForce",
            None,
            *[float(component) / 1000.0 for component in force_per_metre],
        ),
        "GLOBAL_COORDS",
        None,
        "TRUE_LENGTH",
    )
    for relation in model.by_type("IfcRelConnectsStructuralActivity"):
        if relation.RelatedStructuralActivity == point_action:
            relation.RelatedStructuralActivity = action
    for relation in model.by_type("IfcRelAssignsToGroup"):
        if point_action in relation.RelatedObjects:
            relation.RelatedObjects = [
                action if obj == point_action else obj
                for obj in relation.RelatedObjects
            ]
    model.remove(point_action)
    path = str(tmp_path / "line_load.ifc")
    model.write(path)
    return path


class TestFixedFixedBeamLineLoad:
    """beam_01 under a uniform line load given in global axes.

    A distributed load used to be written by magnitude alone, as a pressure
    along the element's own axes, so its direction and sign were lost: every
    line load pushed along the beam's local 2 axis, sideways for a floor beam.
    """

    LOAD = 5000.0  # N/m
    B = TestFixedFixedBeamPointLoad

    def _expected(self) -> float:
        shear_modulus = self.B.E / (2 * (1 + self.B.NU))
        return self.LOAD * self.B.LENGTH**4 / (
            384 * self.B.E * self.B.INERTIA
        ) + self.LOAD * self.B.LENGTH**2 / (8 * shear_modulus * self.B.AREA * 5 / 6)

    def test_vertical_load_deflects_downwards(self, tmp_path):
        path = _beam_with_line_load(tmp_path, (0.0, 0.0, -self.LOAD))
        data = _run(path, tmp_path)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(
            self._expected(), rel=DEFLECTION_TOLERANCE
        )
        assert envelope.get("max_ty_m", 0.0) < 0.01 * envelope["max_tz_m"]
        # The supports push up with the whole load, less the sliver that
        # lands on the restrained end nodes themselves (0.4% at this mesh)
        reaction = data["global_reactions"]["total"]
        assert reaction["fz_N"] == pytest.approx(self.LOAD * self.B.LENGTH, rel=0.01)

    def test_horizontal_load_deflects_sideways(self, tmp_path):
        """Same magnitude along global Y: the square section answers alike."""
        path = _beam_with_line_load(tmp_path, (0.0, self.LOAD, 0.0))
        data = _run(path, tmp_path)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_ty_m"] == pytest.approx(
            self._expected(), rel=DEFLECTION_TOLERANCE
        )
        assert envelope.get("max_tz_m", 0.0) < 0.01 * envelope["max_ty_m"]
        reaction = data["global_reactions"]["total"]
        assert reaction["fy_N"] == pytest.approx(-self.LOAD * self.B.LENGTH, rel=0.01)


PIN = (True, True, True, True, False, False)  # torsion held, bending free
ROLLER = (False, True, True, False, False, False)
BALL = (True, True, True, False, False, False)


def _beam_on_supports(tmp_path, start, end, line_load=None, i_profile=False) -> str:
    """Write beam_01.ifc with new support conditions (dx, dy, dz, drx, dry, drz).

    The point load stays unless ``line_load`` (N/m, along global -Z) replaces it.
    """
    if line_load is None:
        model = ifcopenshell.open(BEAM)
        if i_profile:
            _give_beam_01_an_i_profile(model)
    else:
        model = ifcopenshell.open(
            _beam_with_line_load(tmp_path, (0.0, 0.0, -line_load), i_profile=i_profile)
        )
    supports = sorted(
        model.by_type("IfcStructuralPointConnection"), key=lambda c: c.id()
    )
    for support, fixed in zip(supports, (start, end)):
        support.AppliedCondition = model.create_entity(
            "IfcBoundaryNodeCondition",
            None,
            *[model.create_entity("IfcBoolean", bool(value)) for value in fixed],
        )
    path = str(tmp_path / "supports.ifc")
    model.write(path)
    return path


class TestSimplySupportedBeam:
    """beam_01 on a pin and a roller: the supports every textbook starts with."""

    B = TestFixedFixedBeamPointLoad
    LINE_LOAD = 5000.0  # N/m
    MESH = 0.25

    def _shear_stiffness(self) -> float:
        return self.B.E / (2 * (1 + self.B.NU)) * self.B.AREA * 5 / 6

    def test_point_load(self, tmp_path):
        """P L^3 / 48 E I plus shear; moment P L / 4 and shear P / 2."""
        data = _run(_beam_on_supports(tmp_path, PIN, ROLLER), tmp_path, self.MESH)
        load, length = self.B.LOAD, self.B.LENGTH
        expected = load * length**3 / (48 * self.B.E * self.B.INERTIA) + (
            load * length / (4 * self._shear_stiffness())
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )
        forces = _curve_member_envelope(data)["section_forces"]
        assert forces["max_Mf1_Nm"] == pytest.approx(
            load * length / 4, rel=FORCE_TOLERANCE
        )
        assert forces["max_Vf1_N"] == pytest.approx(load / 2, rel=FORCE_TOLERANCE)
        assert forces["max_N_N"] < 1e-3 * load
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            load, rel=1e-3
        )

    def test_no_moment_at_the_supports(self, tmp_path):
        data = _run(_beam_on_supports(tmp_path, PIN, ROLLER), tmp_path, self.MESH)
        diagram = _curve_member_diagram(data)
        largest = self.B.LOAD * self.B.LENGTH / 4
        assert abs(diagram["Mf1_Nm"][0]) < 0.01 * largest
        assert abs(diagram["Mf1_Nm"][-1]) < 0.01 * largest

    def test_roller_end_moves_along_the_beam(self, tmp_path):
        """Held at both ends the beam cannot shorten; on a roller it does."""
        roller = _run(_beam_on_supports(tmp_path, PIN, ROLLER), tmp_path, self.MESH)
        assert roller["global_displacements"]["envelope"]["max_tx_m"] > 0

    def test_line_load(self, tmp_path):
        """5 w L^4 / 384 E I plus shear; moment w L^2 / 8."""
        path = _beam_on_supports(tmp_path, PIN, ROLLER, line_load=self.LINE_LOAD)
        data = _run(path, tmp_path, self.MESH)
        load, length = self.LINE_LOAD, self.B.LENGTH
        expected = 5 * load * length**4 / (384 * self.B.E * self.B.INERTIA) + (
            load * length**2 / (8 * self._shear_stiffness())
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )
        forces = _curve_member_envelope(data)["section_forces"]
        assert forces["max_Mf1_Nm"] == pytest.approx(
            load * length**2 / 8, rel=FORCE_TOLERANCE
        )

    def test_i_section_line_load(self, tmp_path):
        """A third of the deflection is shear in the web."""
        path = _beam_on_supports(
            tmp_path, PIN, ROLLER, line_load=self.LINE_LOAD, i_profile=True
        )
        data = _run(path, tmp_path, self.MESH)
        load, length = self.LINE_LOAD, self.B.LENGTH
        shear_modulus = self.B.E / (2 * (1 + self.B.NU))
        expected = 5 * load * length**4 / (384 * self.B.E * I_STRONG) + (
            load * length**2 / (8 * shear_modulus * I_H * I_TW)
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )

    def test_supports_that_leave_the_beam_free_to_spin(self, tmp_path):
        """Three translations at each end and nothing else: the usual input.

        Nothing stops the beam turning about its own axis. It used to solve
        anyway, with an arbitrary rotation that more than doubled the
        deflection read on the faces of the section. It is now held in
        torsion at one support, and says so.
        """
        result = analyze_ifc(
            ifc_path=_beam_on_supports(tmp_path, BALL, BALL),
            output_dir=str(tmp_path / "out"),
            mesh_size=self.MESH,
        )
        assert result["status"] == "success", result.get("errors")
        with open(os.path.join(str(tmp_path / "out"), "results.json")) as fh:
            data = json.load(fh)
        load, length = self.B.LOAD, self.B.LENGTH
        expected = load * length**3 / (48 * self.B.E * self.B.INERTIA) + (
            load * length / (4 * self._shear_stiffness())
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )
        messages = [w["message"] for w in result["warnings"]]
        assert any("free to spin about their own axis" in m for m in messages)

    def test_properly_supported_beam_raises_no_such_warning(self, tmp_path):
        result = analyze_ifc(
            ifc_path=_beam_on_supports(tmp_path, PIN, ROLLER),
            output_dir=str(tmp_path / "out"),
            mesh_size=self.MESH,
        )
        assert not any("spin" in w["message"] for w in result["warnings"])


def _inertia_of_rectangles(rectangles):
    """Area and centroidal second moments of a section built of rectangles.

    Each rectangle is ``(x0, x1, y0, y1)``. Returns ``(area, about x, about y)``.
    """
    area = sum((x1 - x0) * (y1 - y0) for x0, x1, y0, y1 in rectangles)
    cx = sum((x1 - x0) * (y1 - y0) * (x0 + x1) / 2 for x0, x1, y0, y1 in rectangles)
    cy = sum((x1 - x0) * (y1 - y0) * (y0 + y1) / 2 for x0, x1, y0, y1 in rectangles)
    cx, cy = cx / area, cy / area
    about_x = sum(
        (x1 - x0) * (y1 - y0) ** 3 / 12
        + (x1 - x0) * (y1 - y0) * ((y0 + y1) / 2 - cy) ** 2
        for x0, x1, y0, y1 in rectangles
    )
    about_y = sum(
        (y1 - y0) * (x1 - x0) ** 3 / 12
        + (x1 - x0) * (y1 - y0) * ((x0 + x1) / 2 - cx) ** 2
        for x0, x1, y0, y1 in rectangles
    )
    return area, about_x, about_y


# T, angle and channel, 200 wide and 400 deep. Each entry: IFC class, its
# attributes, the rectangles the section is made of, and the shear areas for
# loads along the depth and along the width.
_T_WEB, _T_FLANGE, _ANGLE_T = 0.01, 0.02, 0.02
OPEN_SECTIONS = {
    "T": (
        "IfcTShapeProfileDef",
        {
            "Depth": I_H,
            "FlangeWidth": I_B,
            "WebThickness": _T_WEB,
            "FlangeThickness": _T_FLANGE,
        },
        [
            (-I_B / 2, I_B / 2, I_H - _T_FLANGE, I_H),
            (-_T_WEB / 2, _T_WEB / 2, 0.0, I_H - _T_FLANGE),
        ],
        _T_WEB * (I_H - _T_FLANGE),
        I_B * _T_FLANGE,
    ),
    "angle": (
        "IfcLShapeProfileDef",
        {"Depth": I_H, "Width": I_B, "Thickness": _ANGLE_T},
        [(0.0, _ANGLE_T, 0.0, I_H), (_ANGLE_T, I_B, 0.0, _ANGLE_T)],
        2 / 3 * _ANGLE_T * I_H,
        2 / 3 * _ANGLE_T * I_B,
    ),
    "channel": (
        "IfcUShapeProfileDef",
        {
            "Depth": I_H,
            "FlangeWidth": I_B,
            "WebThickness": _T_WEB,
            "FlangeThickness": _T_FLANGE,
        },
        [
            (0.0, _T_WEB, 0.0, I_H),
            (_T_WEB, I_B, 0.0, _T_FLANGE),
            (_T_WEB, I_B, I_H - _T_FLANGE, I_H),
        ],
        I_H * _T_WEB,
        2 * I_B * _T_FLANGE,
    ),
}


class TestTeeAngleAndChannel:
    """cantilever_01 with a T, an angle and a channel, about both axes.

    The reference is beam theory with the section's second moments about its
    centroidal axes parallel to its legs, worked out here from its rectangles.
    For the angle that is the library's assumption, not the whole truth: an
    angle's principal axes are rotated, and a real one also moves sideways.
    """

    @pytest.mark.parametrize("shape", sorted(OPEN_SECTIONS))
    @pytest.mark.parametrize("weak", [False, True], ids=["strong", "weak"])
    def test_self_weight_deflection_and_reaction(self, tmp_path, shape, weak):
        ifc_class, attributes, rectangles, shear_depth, shear_width = OPEN_SECTIONS[
            shape
        ]
        area, strong, weak_inertia = _inertia_of_rectangles(rectangles)
        model = ifcopenshell.open(CANTILEVER)
        if weak:
            member = model.by_type("IfcStructuralCurveMember")[0]
            member.Axis.DirectionRatios = (0.0, 1.0, 0.0)
        model.by_type("IfcMaterialProfile")[0].Profile = model.create_entity(
            ifc_class, ProfileType="AREA", ProfileName=shape, **attributes
        )
        path = str(tmp_path / "variant.ifc")
        model.write(path)
        data = _run(path, tmp_path, gravity=True)
        expected = _cantilever_self_weight(
            area,
            weak_inertia if weak else strong,
            shear_width if weak else shear_depth,
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            CANT_RHO * G_ACCEL * area * CANT_L, rel=0.02
        )

    def test_unsupported_profile_stops_the_analysis(self, tmp_path):
        """A Z section used to be analysed as a 0.1 x 0.2 m rectangle, in silence."""
        model = ifcopenshell.open(CANTILEVER)
        model.by_type("IfcMaterialProfile")[0].Profile = model.create_entity(
            "IfcZShapeProfileDef",
            ProfileType="AREA",
            ProfileName="Z 400",
            Depth=I_H,
            FlangeWidth=I_B,
            WebThickness=_T_WEB,
            FlangeThickness=_T_FLANGE,
        )
        path = str(tmp_path / "z.ifc")
        model.write(path)
        with pytest.raises(Exception, match="IfcZShapeProfileDef.*not supported"):
            analyze_ifc(ifc_path=path, output_dir=str(tmp_path / "out"), gravity=True)


class TestFixedFixedISectionBeam:
    """beam_01 with the I section as an equivalent rectangle, under applied loads."""

    B = TestFixedFixedBeamPointLoad
    LINE_LOAD = 5000.0  # N/m

    def _stiffness(self):
        shear_modulus = self.B.E / (2 * (1 + self.B.NU))
        return self.B.E * I_STRONG, shear_modulus * I_H * I_TW

    def test_point_load(self, tmp_path):
        model = ifcopenshell.open(BEAM)
        _give_beam_01_an_i_profile(model)
        path = str(tmp_path / "i_beam.ifc")
        model.write(path)
        data = _run(path, tmp_path)
        bending, shear = self._stiffness()
        expected = self.B.LOAD * self.B.LENGTH**3 / (
            192 * bending
        ) + self.B.LOAD * self.B.LENGTH / (4 * shear)
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            self.B.LOAD, rel=1e-3
        )

    def test_line_load(self, tmp_path):
        path = _beam_with_line_load(
            tmp_path, (0.0, 0.0, -self.LINE_LOAD), i_profile=True
        )
        data = _run(path, tmp_path)
        bending, shear = self._stiffness()
        expected = self.LINE_LOAD * self.B.LENGTH**4 / (
            384 * bending
        ) + self.LINE_LOAD * self.B.LENGTH**2 / (8 * shear)
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            self.LINE_LOAD * self.B.LENGTH, rel=0.01
        )


def _slab_on_two_cantilevers(tmp_path, inset: float, i_profile: bool = False) -> str:
    """Write a slab that only two cantilever beams lying in it hold up.

    The slab is 5 m x 1 m and 0.1 m thick, at z = 0. The beams (0.2 x 0.4,
    depth vertical) run along its length at ``inset`` from each long edge,
    fully fixed at x = 0. The only connections between slab and beams are the
    two points at the beam tips, as in models that connect a slab at its
    corners and nowhere else. With ``i_profile`` the beams are the 200 x 400
    I section instead.
    """
    model = ifcopenshell.file(schema="IFC4")
    create = model.create_entity
    guid = ifcopenshell.guid.new
    length, width = SOB_L, SOB_B

    up = create("IfcDirection", (0.0, 0.0, 1.0))
    axes = create(
        "IfcAxis2Placement3D",
        create("IfcCartesianPoint", (0.0, 0.0, 0.0)),
        up,
        create("IfcDirection", (1.0, 0.0, 0.0)),
    )
    placement = create("IfcLocalPlacement", None, axes)
    units = create(
        "IfcUnitAssignment",
        [create("IfcSIUnit", None, "LENGTHUNIT", None, "METRE")],
    )
    context = create(
        "IfcGeometricRepresentationContext", None, "Model", 3, 1e-5, axes, None
    )
    project = create(
        "IfcProject",
        guid(),
        None,
        "Benchmark",
        None,
        None,
        None,
        None,
        [context],
        units,
    )
    analysis = create(
        "IfcStructuralAnalysisModel",
        guid(),
        None,
        "Slab on beams",
        None,
        None,
        "NOTDEFINED",
        axes,
        None,
        None,
        placement,
    )
    create("IfcRelDeclares", guid(), None, None, None, project, [analysis])

    material = create("IfcMaterial", "Material", None, None)
    create(
        "IfcMaterialProperties",
        "Pset_MaterialMechanical",
        None,
        [
            create(
                "IfcPropertySingleValue",
                "YoungModulus",
                None,
                create("IfcModulusOfElasticityMeasure", CANT_E),
                None,
            ),
            create(
                "IfcPropertySingleValue",
                "PoissonRatio",
                None,
                create("IfcPositiveRatioMeasure", CANT_NU),
                None,
            ),
        ],
        material,
    )
    create(
        "IfcMaterialProperties",
        "Pset_MaterialCommon",
        None,
        [
            create(
                "IfcPropertySingleValue",
                "MassDensity",
                None,
                create("IfcMassDensityMeasure", CANT_RHO),
                None,
            )
        ],
        material,
    )
    if i_profile:
        profile = create(
            "IfcIShapeProfileDef",
            ProfileType="AREA",
            ProfileName="Beam",
            OverallWidth=I_B,
            OverallDepth=I_H,
            WebThickness=I_TW,
            FlangeThickness=I_TF,
        )
    else:
        profile = create(
            "IfcRectangleProfileDef", "AREA", "Beam", None, SOB_BEAM_B, SOB_BEAM_H
        )
    profile_set = create(
        "IfcMaterialProfileSet",
        None,
        None,
        [create("IfcMaterialProfile", "Beam", None, material, profile, None, None)],
        None,
    )

    def vertex(x, y):
        point = create("IfcCartesianPoint", (float(x), float(y), 0.0))
        return create("IfcVertexPoint", point)

    def shape(kind, item):
        topology = create(
            "IfcTopologyRepresentation", context, "Reference", kind, [item]
        )
        return create("IfcProductDefinitionShape", None, None, [topology])

    def connect(member, connection):
        create(
            "IfcRelConnectsStructuralMember",
            guid(),
            None,
            None,
            None,
            member,
            connection,
            None,
            None,
            None,
            None,
        )

    corners = [
        vertex(x, y) for x, y in ((0, 0), (length, 0), (length, width), (0, width))
    ]
    loop = create(
        "IfcEdgeLoop",
        [
            create(
                "IfcOrientedEdge",
                None,
                None,
                create("IfcEdge", corners[i], corners[(i + 1) % 4]),
                True,
            )
            for i in range(4)
        ],
    )
    face = create(
        "IfcFaceSurface",
        [create("IfcFaceBound", loop, True)],
        create("IfcPlane", axes),
        True,
    )
    slab = create(
        "IfcStructuralSurfaceMember",
        guid(),
        None,
        "Slab",
        None,
        None,
        placement,
        shape("Face", face),
        "SHELL",
        SOB_T,
    )
    create("IfcRelAssociatesMaterial", guid(), None, None, None, [slab], material)

    products, beams = [slab], []
    for y in (inset, width - inset):
        beam = create(
            "IfcStructuralCurveMember",
            guid(),
            None,
            "Beam",
            None,
            None,
            placement,
            shape("Edge", create("IfcEdge", vertex(0, y), vertex(length, y))),
            "RIGID_JOINED_MEMBER",
            up,
        )
        fixed = create(
            "IfcBoundaryNodeCondition",
            None,
            *[create("IfcBoolean", True) for _ in range(6)],
        )
        support = create(
            "IfcStructuralPointConnection",
            guid(),
            None,
            "Support",
            None,
            None,
            placement,
            shape("Vertex", vertex(0, y)),
            fixed,
            None,
        )
        tip = create(
            "IfcStructuralPointConnection",
            guid(),
            None,
            "Tip",
            None,
            None,
            placement,
            shape("Vertex", vertex(length, y)),
            None,
            None,
        )
        connect(beam, support)
        connect(beam, tip)
        connect(slab, tip)
        beams.append(beam)
        products += [beam, support, tip]
    create("IfcRelAssociatesMaterial", guid(), None, None, None, beams, profile_set)
    create("IfcRelAssignsToGroup", guid(), None, None, None, products, None, analysis)

    path = str(tmp_path / "slab_on_beams.ifc")
    model.write(path)
    return path


class TestSlabBearingOnBeams:
    """A slab connected to its beams at two points only still bears on them.

    Read literally the slab would hang from the two beam tips, which is a
    mechanism. Tied along the beams, the three act as one cantilever whose
    stiffness is the sum of the parts (the ties carry no moment and the axes
    are at one level, so there is no composite action).
    """

    MESH = 0.25

    def _expected(self) -> float:
        area = SOB_BEAM_B * SOB_BEAM_H
        inertia = SOB_BEAM_B * SOB_BEAM_H**3 / 12 + SOB_B * SOB_T**3 / 12 / 2
        load = CANT_RHO * G_ACCEL * (area + SOB_T * SOB_B / 2)
        return load * SOB_L**4 / (8 * CANT_E * inertia) + load * SOB_L**2 / (
            2 * CANT_G * 5 / 6 * area
        )

    def test_beams_under_the_slab_edges(self, tmp_path):
        data = _run(
            _slab_on_two_cantilevers(tmp_path, inset=0.0),
            tmp_path,
            mesh_size=self.MESH,
            gravity=True,
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            self._expected(), rel=DEFLECTION_TOLERANCE
        )

    def test_beams_inside_the_slab(self, tmp_path):
        """Beam nodes fall inside shell elements, not on their nodes."""
        data = _run(
            _slab_on_two_cantilevers(tmp_path, inset=0.25),
            tmp_path,
            mesh_size=self.MESH,
            gravity=True,
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            self._expected(), rel=DEFLECTION_TOLERANCE
        )

    def test_supports_carry_the_whole_weight(self, tmp_path):
        data = _run(
            _slab_on_two_cantilevers(tmp_path, inset=0.25),
            tmp_path,
            mesh_size=self.MESH,
            gravity=True,
        )
        weight = (
            CANT_RHO * G_ACCEL * SOB_L * (2 * SOB_BEAM_B * SOB_BEAM_H + SOB_T * SOB_B)
        )
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            weight, rel=0.01
        )

    def test_each_beam_reports_the_deflection(self, tmp_path):
        """results.json gives it per member, for beams as for the slab."""
        data = _run(
            _slab_on_two_cantilevers(tmp_path, inset=0.25),
            tmp_path,
            mesh_size=self.MESH,
            gravity=True,
        )
        beams = [m for m in data["members"] if m["type"] == "curve"]
        assert len(beams) == 2
        for beam in beams:
            assert beam["by_load_case"]["Gravity"][
                "max_displacement_m"
            ] == pytest.approx(self._expected(), rel=DEFLECTION_TOLERANCE)
            assert beam["by_load_case"]["Gravity"]["max_von_mises_Pa"] > 0

    def test_i_section_beams_mixed_with_a_slab(self, tmp_path):
        """A model stock CalculiX could not run with U1 elements at all.

        The I sections are equivalent rectangles. Each beam takes its own weight and half
        the slab's, with its strong-axis stiffness and its web in shear.
        """
        result = analyze_ifc(
            ifc_path=_slab_on_two_cantilevers(tmp_path, inset=0.25, i_profile=True),
            output_dir=str(tmp_path / "out"),
            mesh_size=self.MESH,
            gravity=True,
        )
        assert result["status"] == "success", result.get("errors")
        with open(os.path.join(str(tmp_path / "out"), "analysis.inp")) as fh:
            assert "TYPE=U1" not in fh.read()
        with open(os.path.join(str(tmp_path / "out"), "results.json")) as fh:
            data = json.load(fh)
        inertia = I_STRONG + SOB_B * SOB_T**3 / 12 / 2
        load = CANT_RHO * G_ACCEL * (I_AREA + SOB_T * SOB_B / 2)
        expected = load * SOB_L**4 / (8 * CANT_E * inertia) + load * SOB_L**2 / (
            2 * CANT_G * I_H * I_TW
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )
        weight = CANT_RHO * G_ACCEL * SOB_L * (2 * I_AREA + SOB_T * SOB_B)
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            weight, rel=0.01
        )
        messages = [w["message"] for w in result["warnings"]]
        assert any(
            "2 member(s) whose section is not a solid rectangle" in m for m in messages
        )

    def test_strict_connections_tie_nothing(self, tmp_path):
        """Only the two tip connections of the file join slab and beams."""
        output_dir = str(tmp_path / "out")
        result = analyze_ifc(
            ifc_path=_slab_on_two_cantilevers(tmp_path, inset=0.25),
            output_dir=output_dir,
            mesh_size=self.MESH,
            gravity=True,
            strict_connections=True,
        )
        assert result["status"] == "success", result.get("errors")
        messages = [w["message"] for w in result["warnings"]]
        assert any("left unconnected" in m for m in messages)
        with open(os.path.join(output_dir, "analysis.inp")) as fh:
            assert "bearing on the surface member" not in fh.read()

    def test_the_assumption_is_reported(self, tmp_path):
        result = analyze_ifc(
            ifc_path=_slab_on_two_cantilevers(tmp_path, inset=0.0),
            output_dir=str(tmp_path / "out"),
            mesh_size=self.MESH,
            gravity=True,
        )
        messages = [w["message"] for w in result["warnings"]]
        assert any("2 curve member(s) lie in a surface member" in m for m in messages)


def _balcony_frame(tmp_path, profile_class, profile_attributes) -> str:
    """Write a cantilever with an arm at right angles on its tip, loaded at the end.

    Member A runs 3 m along X from a fixed support; member B runs 1 m along Y
    from A's tip, rigidly joined to it; 1 kN acts downwards on B's free end.
    The load bends both and twists A with a torque of 1 kN m. Units are m, N
    and Pa, steel.
    """
    model = ifcopenshell.file(schema="IFC4")
    create = model.create_entity
    guid = ifcopenshell.guid.new
    up = create("IfcDirection", (0.0, 0.0, 1.0))
    axes = create(
        "IfcAxis2Placement3D",
        create("IfcCartesianPoint", (0.0, 0.0, 0.0)),
        up,
        create("IfcDirection", (1.0, 0.0, 0.0)),
    )
    placement = create("IfcLocalPlacement", None, axes)
    units = create(
        "IfcUnitAssignment", [create("IfcSIUnit", None, "LENGTHUNIT", None, "METRE")]
    )
    context = create(
        "IfcGeometricRepresentationContext", None, "Model", 3, 1e-5, axes, None
    )
    project = create(
        "IfcProject",
        guid(),
        None,
        "Benchmark",
        None,
        None,
        None,
        None,
        [context],
        units,
    )
    case = create(
        "IfcStructuralLoadCase",
        GlobalId=guid(),
        Name="Tip load",
        PredefinedType="LOAD_CASE",
        ActionType="VARIABLE_Q",
        ActionSource="LIVE_LOAD_Q",
    )
    analysis = create(
        "IfcStructuralAnalysisModel",
        guid(),
        None,
        "Balcony",
        None,
        None,
        "NOTDEFINED",
        axes,
        [case],
        None,
        placement,
    )
    create("IfcRelDeclares", guid(), None, None, None, project, [analysis])

    material = create("IfcMaterial", "Steel", None, None)
    create(
        "IfcMaterialProperties",
        "Pset_MaterialMechanical",
        None,
        [
            create(
                "IfcPropertySingleValue",
                "YoungModulus",
                None,
                create("IfcModulusOfElasticityMeasure", TORSION_E),
                None,
            ),
            create(
                "IfcPropertySingleValue",
                "PoissonRatio",
                None,
                create("IfcPositiveRatioMeasure", TORSION_NU),
                None,
            ),
        ],
        material,
    )
    profile = create(
        profile_class, ProfileType="AREA", ProfileName="Section", **profile_attributes
    )
    profile_set = create(
        "IfcMaterialProfileSet",
        None,
        None,
        [create("IfcMaterialProfile", "Section", None, material, profile, None, None)],
        None,
    )

    def vertex(point):
        return create(
            "IfcVertexPoint",
            create("IfcCartesianPoint", tuple(float(v) for v in point)),
        )

    def shape(kind, item):
        topology = create(
            "IfcTopologyRepresentation", context, "Reference", kind, [item]
        )
        return create("IfcProductDefinitionShape", None, None, [topology])

    def member(start, end):
        return create(
            "IfcStructuralCurveMember",
            guid(),
            None,
            "Member",
            None,
            None,
            placement,
            shape("Edge", create("IfcEdge", vertex(start), vertex(end))),
            "RIGID_JOINED_MEMBER",
            up,
        )

    def connection(point, fixed):
        condition = (
            create(
                "IfcBoundaryNodeCondition",
                None,
                *[create("IfcBoolean", True) for _ in range(6)],
            )
            if fixed
            else None
        )
        return create(
            "IfcStructuralPointConnection",
            guid(),
            None,
            "Connection",
            None,
            None,
            placement,
            shape("Vertex", vertex(point)),
            condition,
            None,
        )

    def connect(structural_member, structural_connection):
        create(
            "IfcRelConnectsStructuralMember",
            guid(),
            None,
            None,
            None,
            structural_member,
            structural_connection,
            None,
            None,
            None,
            None,
        )

    root, corner, tip = (0, 0, 0), (TORSION_LA, 0, 0), (TORSION_LA, TORSION_LB, 0)
    main, arm = member(root, corner), member(corner, tip)
    support, joint = connection(root, True), connection(corner, False)
    connect(main, support)
    connect(main, joint)
    connect(arm, joint)
    create(
        "IfcRelAssociatesMaterial", guid(), None, None, None, [main, arm], profile_set
    )

    action = create(
        "IfcStructuralPointAction",
        GlobalId=guid(),
        Name="Tip load",
        ObjectPlacement=placement,
        Representation=shape("Vertex", vertex(tip)),
        AppliedLoad=create(
            "IfcStructuralLoadSingleForce", None, 0.0, 0.0, -TORSION_P, 0.0, 0.0, 0.0
        ),
        GlobalOrLocal="GLOBAL_COORDS",
    )
    create("IfcRelConnectsStructuralActivity", guid(), None, None, None, arm, action)
    create("IfcRelAssignsToGroup", guid(), None, None, None, [action], None, case)
    create(
        "IfcRelAssignsToGroup",
        guid(),
        None,
        None,
        None,
        [main, arm, support, joint],
        None,
        analysis,
    )
    path = str(tmp_path / "balcony.ifc")
    model.write(path)
    return path


def _slab_on_unconnected_columns(tmp_path, top: float) -> str:
    """Write slab_01 standing on four columns that the file does not connect to it.

    The slab's own supports are removed. Four 0.3 m square columns, fixed at
    z = -3, stand under its quarter points and run up to ``top``: 0 to end on
    the slab, more to pass through it.
    """
    model = ifcopenshell.open(SLAB)
    slab = model.by_type("IfcStructuralSurfaceMember")[0]
    group = model.by_type("IfcRelAssignsToGroup")[0]
    for relation in model.by_type("IfcRelConnectsStructuralMember"):
        model.remove(relation)
    for connection in model.by_type("IfcStructuralCurveConnection"):
        group.RelatedObjects = [o for o in group.RelatedObjects if o != connection]
        model.remove(connection)
    history = slab.OwnerHistory
    context = slab.Representation.Representations[0].ContextOfItems
    material = model.by_type("IfcMaterial")[0]
    profile = model.create_entity(
        "IfcRectangleProfileDef", "AREA", "Column", None, COLUMN_SIDE, COLUMN_SIDE
    )
    profile_set = model.create_entity(
        "IfcMaterialProfileSet",
        None,
        None,
        [
            model.create_entity(
                "IfcMaterialProfile", "Column", None, material, profile, None, None
            )
        ],
        None,
    )

    def vertex(point):
        return model.create_entity(
            "IfcVertexPoint",
            model.create_entity("IfcCartesianPoint", tuple(float(v) for v in point)),
        )

    def shape(kind, item):
        return model.create_entity(
            "IfcProductDefinitionShape",
            None,
            None,
            [
                model.create_entity(
                    "IfcTopologyRepresentation", context, "Reference", kind, [item]
                )
            ],
        )

    columns, added = [], []
    for x, y in COLUMN_POSITIONS:
        base = (x, y, -COLUMN_HEIGHT)
        column = model.create_entity(
            "IfcStructuralCurveMember",
            ifcopenshell.guid.new(),
            history,
            "Column",
            None,
            None,
            slab.ObjectPlacement,
            shape(
                "Edge",
                model.create_entity("IfcEdge", vertex(base), vertex((x, y, top))),
            ),
            "RIGID_JOINED_MEMBER",
            model.create_entity("IfcDirection", (1.0, 0.0, 0.0)),
        )
        support = model.create_entity(
            "IfcStructuralPointConnection",
            ifcopenshell.guid.new(),
            history,
            "Base",
            None,
            None,
            slab.ObjectPlacement,
            shape("Vertex", vertex(base)),
            model.create_entity(
                "IfcBoundaryNodeCondition",
                None,
                *[model.create_entity("IfcBoolean", True) for _ in range(6)],
            ),
            None,
        )
        model.create_entity(
            "IfcRelConnectsStructuralMember",
            ifcopenshell.guid.new(),
            history,
            None,
            None,
            column,
            support,
            None,
            None,
            None,
            None,
        )
        columns.append(column)
        added += [column, support]
    model.create_entity(
        "IfcRelAssociatesMaterial",
        ifcopenshell.guid.new(),
        history,
        None,
        None,
        columns,
        profile_set,
    )
    group.RelatedObjects = list(group.RelatedObjects) + added
    path = str(tmp_path / "columns.ifc")
    model.write(path)
    return path


class TestColumnsMeetingASlabWithNoConnection:
    """A slab held up by nothing but columns the file does not connect to it.

    By symmetry each column carries a quarter of the slab. Read literally the
    slab is not supported at all.
    """

    SLAB_WEIGHT = 7.8 * G_ACCEL * 5.0 * 3.0 * 0.2
    COLUMN_WEIGHT_PER_METRE = 7.8 * G_ACCEL * COLUMN_SIDE**2

    def _analyse(self, tmp_path, top, **kwargs):
        output_dir = str(tmp_path / "out")
        result = analyze_ifc(
            ifc_path=_slab_on_unconnected_columns(tmp_path, top),
            output_dir=output_dir,
            mesh_size=0.5,
            gravity=True,
            **kwargs,
        )
        data = None
        if result["status"] == "success":
            with open(os.path.join(output_dir, "results.json")) as fh:
                data = json.load(fh)
        return result, data

    def test_columns_ending_on_the_slab_each_carry_a_quarter(self, tmp_path):
        result, data = self._analyse(tmp_path, top=0.0)
        assert result["status"] == "success", result.get("errors")
        columns = [m for m in data["members"] if m["type"] == "curve"]
        assert len(columns) == 4
        at_the_base = (
            self.SLAB_WEIGHT / 4 + self.COLUMN_WEIGHT_PER_METRE * COLUMN_HEIGHT
        )
        for column in columns:
            forces = column["envelope"]["section_forces"]
            assert forces["max_compression_N"] == pytest.approx(at_the_base, rel=0.02)
            assert forces["max_tension_N"] < 0.01 * at_the_base
        messages = [w["message"] for w in result["warnings"]]
        assert any(
            "4 curve member(s) meet a surface member at a point" in m for m in messages
        )

    def test_columns_passing_through_the_slab(self, tmp_path):
        """The part above the slab adds its own weight and nothing else."""
        result, data = self._analyse(tmp_path, top=1.0)
        assert result["status"] == "success", result.get("errors")
        at_the_base = self.SLAB_WEIGHT / 4 + self.COLUMN_WEIGHT_PER_METRE * (
            COLUMN_HEIGHT + 1.0
        )
        for column in (m for m in data["members"] if m["type"] == "curve"):
            assert column["envelope"]["section_forces"][
                "max_compression_N"
            ] == pytest.approx(at_the_base, rel=0.02)

    def test_reaction_is_the_weight_of_everything(self, tmp_path):
        _, data = self._analyse(tmp_path, top=0.0)
        total = self.SLAB_WEIGHT + 4 * self.COLUMN_WEIGHT_PER_METRE * COLUMN_HEIGHT
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            total, rel=0.01
        )

    def test_strict_connections_leave_the_slab_in_the_air(self, tmp_path):
        """Nothing holds it. The solver still returns numbers; the result says so."""
        result, _ = self._analyse(tmp_path, top=0.0, strict_connections=True)
        messages = [w["message"] for w in result["warnings"]]
        assert any("left unconnected there" in m for m in messages)
        assert any("probably a mechanism" in m for m in messages)


class TestTorsion:
    """A cantilever twisted by a load on an arm at its tip.

    Statics gives the torque in the cantilever (P Lb) and the moments at the
    two roots (P La and P Lb) whatever the stiffness. The rate at which the
    cantilever twists, read from the solver's own nodes at two of its
    cross-sections, gives the torsional stiffness the analysis used.

    The tip deflection is not used for that: it is read on the faces of the
    expanded elements, where the arm's rotation adds to it, and that once
    made a square section 18 % too stiff look right.
    """

    MESH = 0.125
    SHEAR_MODULUS = TORSION_E / (2 * (1 + TORSION_NU))

    def _run(self, tmp_path, profile_class, attributes):
        path = _balcony_frame(tmp_path, profile_class, attributes)
        return _run(path, tmp_path, mesh_size=self.MESH)

    def _torsion_constant_used(self, tmp_path) -> float:
        """J backed out of the twist between two cross-sections of the cantilever."""
        frd = str(tmp_path / f"out_{self.MESH}" / "analysis.frd")
        parser = ResultsParser()
        coordinates = parser.parse_node_coordinates(frd)
        vertical = {
            int(result.reference_element): result.get_translations()[2]
            for result in parser.parse_displacements(frd)
        }
        twists = []
        for target in (TORSION_LA / 3, 2 * TORSION_LA / 3):
            station = min(
                (xyz[0] for xyz in coordinates.values() if abs(xyz[1]) < 0.5),
                key=lambda x: abs(x - target),
            )
            nodes = [
                node
                for node, xyz in coordinates.items()
                if abs(xyz[0] - station) < 1e-6 and node in vertical
            ]
            slope = np.polyfit(
                [coordinates[node][1] for node in nodes],
                [vertical[node] for node in nodes],
                1,
            )[0]
            twists.append((station, slope))
        (x1, twist1), (x2, twist2) = twists
        rate = abs((twist2 - twist1) / (x2 - x1))
        return TORSION_P * TORSION_LB / (self.SHEAR_MODULUS * rate)

    def test_torque_and_moments_follow_from_statics(self, tmp_path):
        data = self._run(tmp_path, "IfcRectangleProfileDef", {"XDim": 0.3, "YDim": 0.3})
        main, arm = (m["envelope"]["section_forces"] for m in data["members"])
        assert main["max_T_Nm"] == pytest.approx(
            TORSION_P * TORSION_LB, rel=FORCE_TOLERANCE
        )
        assert main["max_Mf1_Nm"] == pytest.approx(
            TORSION_P * TORSION_LA, rel=FORCE_TOLERANCE
        )
        assert arm["max_Mf1_Nm"] == pytest.approx(
            TORSION_P * TORSION_LB, rel=FORCE_TOLERANCE
        )
        assert arm["max_T_Nm"] < 1e-3 * TORSION_P * TORSION_LB

    @pytest.mark.parametrize(
        "width, depth, saint_venant",
        [
            (0.3, 0.3, 0.1406 * 0.3**4),
            (0.2, 0.4, 0.229 * 0.4 * 0.2**3),
            (0.4, 0.2, 0.229 * 0.4 * 0.2**3),
        ],
        ids=["square", "deep", "flat"],
    )
    @pytest.mark.parametrize("element_order", [2, 1])
    def test_solid_rectangle_twists_as_saint_venant_says(
        self, tmp_path, width, depth, saint_venant, element_order
    ):
        """CalculiX's own rectangle is 16 to 18.5 % too stiff (`aiz.53`).

        One solid element across the section can only warp as x2 * x3, which
        gives J = a^3 b^3 / 3 (a^2 + b^2). The writer lowers the shear modulus
        across the width to bring that down to Saint-Venant's value.
        """
        path = _balcony_frame(
            tmp_path, "IfcRectangleProfileDef", {"XDim": width, "YDim": depth}
        )
        _run(path, tmp_path, mesh_size=self.MESH, element_order=element_order)
        assert self._torsion_constant_used(tmp_path) == pytest.approx(
            saint_venant, rel=0.01
        )
        assert (
            expanded_rectangle_torsion_stiffness(depth, width, 1.0, 1.0)
            > 1.1 * saint_venant
        )

    @pytest.mark.parametrize(
        "profile_class, attributes, torsion_constant",
        [
            (
                "IfcCircleHollowProfileDef",
                {"Radius": 0.15, "WallThickness": 0.01},
                math.pi / 2 * (0.15**4 - 0.14**4),
            ),
            (
                "IfcRectangleHollowProfileDef",
                {"XDim": 0.2, "YDim": 0.4, "WallThickness": 0.01},
                4 * (0.19 * 0.39) ** 2 * 0.01 / (2 * (0.19 + 0.39)),
            ),
            ("IfcCircleProfileDef", {"Radius": 0.1}, math.pi / 2 * 0.1**4),
        ],
        ids=["tube", "box", "round bar"],
    )
    def test_closed_and_round_sections_twist_as_theory_says(
        self, tmp_path, profile_class, attributes, torsion_constant
    ):
        """Their equivalent rectangle is given the section's torsion constant."""
        data = self._run(tmp_path, profile_class, attributes)
        assert self._torsion_constant_used(tmp_path) == pytest.approx(
            torsion_constant, rel=0.01
        )
        main = data["members"][0]["envelope"]["section_forces"]
        assert main["max_T_Nm"] == pytest.approx(
            TORSION_P * TORSION_LB, rel=FORCE_TOLERANCE
        )

    def test_open_section_is_far_too_stiff_in_torsion(self, tmp_path):
        """Not a pass mark: the size of an error the README owns up to.

        An I section's equivalent rectangle has its bending and shear
        stiffness; nothing can give it the section's torsional stiffness as
        well. This pins how far off it is, so that a change is noticed.
        """
        data = self._run(
            tmp_path,
            "IfcIShapeProfileDef",
            {
                "OverallWidth": I_B,
                "OverallDepth": I_H,
                "WebThickness": I_TW,
                "FlangeThickness": I_TF,
            },
        )
        torsion_constant = (2 * I_B * I_TF**3 + (I_H - 2 * I_TF) * I_TW**3) / 3
        ratio = self._torsion_constant_used(tmp_path) / torsion_constant
        assert ratio == pytest.approx(29.9, rel=0.05)
        main = data["members"][0]["envelope"]["section_forces"]
        assert main["max_T_Nm"] == pytest.approx(
            TORSION_P * TORSION_LB, rel=FORCE_TOLERANCE
        )


class TestSimplySupportedPlateSelfWeight:
    """slab_01 supported in translation along all four edges, under gravity.

    This is the check on shell bending. Linear S3 shells gave about half the
    deflection at a 0.5 m mesh and were still 20 % short at 0.25 m.
    """

    A, B, T = 5.0, 3.0, 0.2
    E, NU, RHO = 2.1e8, 0.2, 7.8
    PINNED = (True, True, True, False, False, False)

    def _plate(self, tmp_path, area_load=None) -> str:
        return _slab_variant(
            tmp_path,
            edge_conditions=(self.PINNED, self.PINNED),
            extra_edges=(
                ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0), self.PINNED),
                ((0.0, 3.0, 0.0), (5.0, 3.0, 0.0), self.PINNED),
            ),
            area_load=area_load,
        )

    def _centre_deflection(self, q=None) -> float:
        """Navier series for the centre, with the Mindlin shear deflection."""
        if q is None:
            q = self.RHO * G_ACCEL * self.T
        rigidity = self.E * self.T**3 / (12 * (1 - self.NU**2))
        shear_stiffness = 5 / 6 * self.E / (2 * (1 + self.NU)) * self.T
        bending = moment_sum = 0.0
        for m in range(1, 60, 2):
            for n in range(1, 60, 2):
                sign = (-1) ** ((m + n) // 2 - 1)
                k = (m / self.A) ** 2 + (n / self.B) ** 2
                bending += sign / (m * n * k**2)
                moment_sum += sign / (m * n * k)
        return 16 * q / math.pi**6 / rigidity * bending + (
            16 * q / math.pi**4 / shear_stiffness * moment_sum
        )

    def test_centre_deflection(self, tmp_path):
        data = _run(self._plate(tmp_path), tmp_path, mesh_size=0.5, gravity=True)
        assert _max_vertical_deflection(data) == pytest.approx(
            self._centre_deflection(), rel=0.05
        )

    def test_area_load(self, tmp_path):
        """The same plate under an IfcStructuralPlanarAction of 2.5 kPa.

        Checks an area load end to end: its direction, its total (the
        reaction) and the deflection it causes.
        """
        pressure = 2.5
        path = self._plate(tmp_path, area_load=(0.0, 0.0, -pressure))
        data = _run(path, tmp_path, mesh_size=0.5)
        assert data["load_cases"] == ["Imposed"]
        assert _max_vertical_deflection(data) == pytest.approx(
            self._centre_deflection(pressure), rel=0.05
        )
        # The corners of a simply supported plate are held down, and a load on
        # a restrained edge node goes straight to ground, so the reported
        # total is a little short of the load
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            pressure * self.A * self.B, rel=0.1
        )

    def test_area_load_sideways_does_not_bend_the_plate(self, tmp_path):
        """Given along global X, the same load acts in the plane of the slab."""
        path = self._plate(tmp_path, area_load=(2.5, 0.0, 0.0))
        data = _run(path, tmp_path, mesh_size=0.5)
        envelope = data["global_displacements"]["envelope"]
        assert envelope.get("max_tz_m", 0.0) < 1e-3 * self._centre_deflection(2.5)

    def test_converges_from_below(self, tmp_path):
        """Halving the mesh size moves the answer by little, and upwards."""
        path = self._plate(tmp_path)
        coarse, medium, fine = (
            _max_vertical_deflection(_run(path, tmp_path, mesh_size=h, gravity=True))
            for h in (1.0, 0.5, 0.25)
        )
        assert coarse < medium < fine
        assert fine - medium < medium - coarse
        assert fine == pytest.approx(medium, rel=0.02)


class TestCodeAsterReferences:
    """Self-weight results against the Code_Aster runs shipped with the models.

    ``examples/analysis-models/models/<name>/<name>.rmed`` holds IfcOpenShell's
    IFC2CA results for the same IFC files (Euler beams, DKT shells, gravity
    9.806 m/s2). The numbers below are the largest nodal translation in each
    file, read with h5py from ``CHA/Bld_DISP`` (six components per node,
    stored component by component).
    """

    STRUCTURE = os.path.join(IFC_DIR, "structure_01.ifc")
    GRID = os.path.join(IFC_DIR, "grid_of_beams.ifc")

    def test_cantilever_01(self, tmp_path):
        """Reference 0.2766 mm; ours is slightly larger for shear deflection."""
        data = _run(CANTILEVER, tmp_path, gravity=True)
        assert _max_vertical_deflection(data) == pytest.approx(2.766e-4, rel=0.03)

    def test_structure_01(self, tmp_path):
        """Slab hinged on a wall and carried by two columns. Reference 0.4273 mm.

        This one model exercises a line support given in the axes of its edge,
        a slab released along the edge it shares with a wall, a pin-ended
        column (released on the member side of a fixed support) and a column
        joined to the slab by a rigid link. Getting any of them wrong moves
        the answer by 10 % or more; with linear shells and all of them wrong
        it ranged from 0.37 to 0.56 mm depending on the mesh.
        """
        data = _run(self.STRUCTURE, tmp_path, mesh_size=0.5, gravity=True)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_displacement_m"] == pytest.approx(4.273e-4, rel=0.05)
        assert envelope["max_tz_m"] == pytest.approx(4.219e-4, rel=0.05)
        # Sway is the sensitive part. The reference has 0.07 mm at mid-surface
        # (ours adds the slab faces, half a thickness off it); it was 0.34 mm
        # while the wall base was free to rotate about its edge.
        assert envelope["max_tx_m"] < 1.5e-4

    def test_structure_01_member_by_member(self, tmp_path):
        """Each member's largest displacement in results.json, reference in mm.

        The reference values are the largest over the nodes of each member in
        the Code_Aster result. Ours are read on the faces of the expanded
        elements, which adds to it where a member rotates: the pin-ended
        Column_01 is 3 % above the reference at its axis and 8 % on its faces.
        """
        data = _run(self.STRUCTURE, tmp_path, mesh_size=0.5, gravity=True)
        reference_mm = {
            "Slab_01": 0.4273,
            "Wall_01": 0.0764,
            "Column_01": 0.0770,
            "Column_02": 0.0898,
        }
        names = {
            entity.GlobalId: entity.Name
            for entity in ifcopenshell.open(self.STRUCTURE).by_type(
                "IfcStructuralMember"
            )
        }
        assert len(data["members"]) == 4
        for member in data["members"]:
            expected = reference_mm[names[member["ifc_guid"]]] * 1e-3
            assert member["envelope"]["max_displacement_m"] == pytest.approx(
                expected, rel=0.10
            ), names[member["ifc_guid"]]

    def test_structure_01_converges(self, tmp_path):
        """Refining the mesh changes the answer by little, and less each time."""
        coarse, medium, fine = (
            _run(self.STRUCTURE, tmp_path, mesh_size=h, gravity=True)[
                "global_displacements"
            ]["envelope"]["max_displacement_m"]
            for h in (1.0, 0.5, 0.25)
        )
        assert coarse < medium < fine
        assert fine - medium < medium - coarse
        assert fine == pytest.approx(medium, rel=0.02)

    def test_grid_of_beams(self, tmp_path):
        """Five secondary beams hinged onto two clamped main beams. Reference 0.3963 mm.

        Each secondary beam ends 0.15 m to the side of and above the main
        beam's axis and is released there in bending only: a single-axis hinge
        on a rigid lever arm, framing into the main beam's span.

        The reference is 0.029 mm too high. Its rigid arms were given a 1 m
        square section and the model's density, so each weighs 16 N, more
        than the 11 N a secondary beam delivers. That extra load is worked out
        here for the clamped main beam (three interior joints) and taken off.
        """
        arm_weight = 1.0 * math.hypot(0.15, 0.15) * CANT_RHO * 9.806
        span, quarter = 5.8, 1.45
        stiffness = CANT_E * 0.3 * 0.6**3 / 12
        spurious = arm_weight * span**3 / (192 * stiffness) + (
            2 * arm_weight * quarter**2 * (3 * span - 4 * quarter) / (48 * stiffness)
        )
        assert spurious == pytest.approx(0.29e-4, rel=0.02)

        results = [
            _run(self.GRID, tmp_path, mesh_size=h, gravity=True)[
                "global_displacements"
            ]["envelope"]["max_displacement_m"]
            for h in (1.0, 0.5, 0.25)
        ]
        assert results[1] == pytest.approx(3.963e-4 - spurious, rel=0.03)
        # Used to be 0.49, 0.33 and 1.38 mm: the pinned beams could spin
        assert max(results) == pytest.approx(min(results), rel=0.01)

    def test_slab_01_with_the_supports_of_the_reference(self, tmp_path):
        """One-way slab clamped at x = 0 and hinged at x = 5. Reference 0.3761 mm.

        The Code_Aster run was made from an earlier slab_01.ifc. Today's file
        fixes both supports and releases the slab about the two axes that do
        not matter, which clamps both ends and gives half the deflection
        (0.18 mm, ``w L^4 / 384 E I``). The conditions of the reference run are
        restored here.
        """
        path = _slab_variant(
            tmp_path,
            edge_conditions=(
                (True, True, True, True, False, False),
                (True, True, True, False, False, False),
            ),
        )
        data = _run(path, tmp_path, mesh_size=0.5, gravity=True)
        assert _max_vertical_deflection(data) == pytest.approx(3.761e-4, rel=0.03)

    def test_slab_01_as_authored_is_clamped_at_both_ends(self, tmp_path):
        """Beam theory for a 5 m span clamped at both ends, per metre width."""
        data = _run(SLAB, tmp_path, mesh_size=0.5, gravity=True)
        thickness, span, modulus, poisson = 0.2, 5.0, 2.1e8, 0.2
        load = CANT_RHO * G_ACCEL * thickness
        shear_modulus = modulus / (2 * (1 + poisson))
        expected = load * span**4 / (384 * modulus * thickness**3 / 12) + (
            load * span**2 / (8 * shear_modulus * thickness * 5 / 6)
        )
        assert _max_vertical_deflection(data) == pytest.approx(expected, rel=0.03)

    def test_structure_01_supports_and_joints(self, tmp_path):
        """The wall base is a line support; the slab-to-wall joint is no support."""
        output_dir = str(tmp_path / "out")
        analyze_ifc(
            ifc_path=self.STRUCTURE, output_dir=output_dir, mesh_size=0.5, gravity=True
        )
        with open(os.path.join(output_dir, "analysis.inp")) as fh:
            text = fh.read()
        support_sets = {}
        support_dofs = {}
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
            elif line.startswith("BC_"):
                name, first, last = (part.strip() for part in line.split(","))
                support_dofs.setdefault(name, []).extend(
                    range(int(first), int(last) + 1)
                )
        by_size = sorted(support_dofs, key=lambda name: support_sets[name])
        # Wall base: translations and rotation about the edge, which runs
        # along global Y. Column_01: fixed support, member released in both
        # bending rotations, so only torsion (about Z) is held. Column_02: fixed.
        assert support_dofs[by_size[-1]] == [1, 2, 3, 5]
        assert sorted(support_dofs[name] for name in by_size[:2]) == [
            [1, 2, 3, 4, 5, 6],
            [1, 2, 3, 6],
        ]
        # Wall base edge plus two column bases; the slab-wall joint has no
        # AppliedCondition and must not appear.
        assert len(support_sets) == 3
        assert sorted(support_sets.values())[:2] == [1, 1]
        assert max(support_sets.values()) > 2
        # Weight: 6 m3 of slab and 2.4 m3 of wall at 7.8 kg/m3, plus columns
        with open(os.path.join(output_dir, "results.json")) as fh:
            reaction = json.load(fh)["global_reactions"]["total"]["fz_N"]
        assert 600 < reaction < 700


def _placed_variant(tmp_path, name: str) -> str:
    """An example with every item under a placement that moves and turns it.

    The placement is nested: its parent is 12, -7, 3 m away and a quarter
    turn about Z, and it adds 1.5, 2.5, -0.5 m in the parent's axes. Offsets
    are written in the file's own length unit.
    """
    import ifcopenshell
    import ifcopenshell.util.unit

    model = ifcopenshell.open(os.path.join(IFC_DIR, f"{name}.ifc"))
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)

    def axes(offset, x_axis):
        return model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity(
                "IfcCartesianPoint", [c / scale for c in offset]
            ),
            Axis=model.create_entity("IfcDirection", (0.0, 0.0, 1.0)),
            RefDirection=model.create_entity("IfcDirection", x_axis),
        )

    parent = model.create_entity(
        "IfcLocalPlacement", RelativePlacement=axes((12.0, -7.0, 3.0), (0.0, 1.0, 0.0))
    )
    placement = model.create_entity(
        "IfcLocalPlacement",
        PlacementRelTo=parent,
        RelativePlacement=axes((1.5, 2.5, -0.5), (1.0, 0.0, 0.0)),
    )
    for kind in ("IfcStructuralItem", "IfcStructuralActivity"):
        for entity in model.by_type(kind):
            entity.ObjectPlacement = placement
    path = str(tmp_path / f"{name}_placed.ifc")
    model.write(path)
    return path


class TestPlacedModel:
    """A model moved and turned by its placements is the same structure.

    The examples keep every placement at the origin, which hid three faults
    (``aiz.57``): a member's offset was added without converting it to
    metres, supports and loads ignored their placement, and a parent
    placement was not applied. The quarter turn swaps global X and Y, so the
    supports stay in axes the writer can restrain.
    """

    @pytest.mark.parametrize(
        "name, gravity",
        [("beam_01", False), ("portal_01", True), ("structure_01", True)],
        ids=["beam_01 (mm)", "portal_01 (inches)", "structure_01 (m)"],
    )
    def test_results_are_those_of_the_model_as_shipped(self, tmp_path, name, gravity):
        mesh = 0.5 if name == "structure_01" else 0.25
        shipped = _run(
            os.path.join(IFC_DIR, f"{name}.ifc"),
            tmp_path / "shipped",
            mesh_size=mesh,
            gravity=gravity,
        )
        placed = _run(
            _placed_variant(tmp_path, name),
            tmp_path / "placed",
            mesh_size=mesh,
            gravity=gravity,
        )

        before = shipped["global_displacements"]["envelope"]
        after = placed["global_displacements"]["envelope"]
        # The mesh of a surface is not the same after the move
        tolerance = 0.002
        for moved, original in (("tx", "ty"), ("ty", "tx"), ("tz", "tz")):
            assert after[f"max_{moved}_m"] == pytest.approx(
                before[f"max_{original}_m"], rel=tolerance, abs=1e-9
            )

        reactions = placed["global_reactions"]["by_load_case"]
        assert set(reactions) == set(shipped["global_reactions"]["by_load_case"])
        for case, reaction in shipped["global_reactions"]["by_load_case"].items():
            assert reactions[case]["fz_N"] == pytest.approx(reaction["fz_N"], rel=1e-4)
            assert abs(reactions[case]["fx_N"]) < 1e-3
            assert abs(reactions[case]["fy_N"]) < 1e-3
        assert len(placed["members"]) == len(shipped["members"])
