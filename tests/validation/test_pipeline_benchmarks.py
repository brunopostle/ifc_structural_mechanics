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
* Natural frequencies: Timoshenko's beam and Mindlin's plate, simply
  supported, in closed form; a Timoshenko cantilever by finite elements
  (``_timoshenko_cantilever_frequencies``); rods in tension and torsion
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
    rectangle_shear_moduli,
)
from ifc_structural_mechanics.domain.property import Section  # noqa: E402
from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
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
from tests.helpers import (  # noqa: E402
    PLANE_FIXED,
    PLANE_FIXED_2D,
    PLANE_PIN,
    PLANE_PIN_2D,
    PLANE_ROLLER,
    PLANE_ROLLER_2D,
    plane_model,
    solver_reports_clamped_reactions,
)

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


def _beam_01(self_weight: bool = False):
    """Open beam_01.ifc, by default without the self-weight in its Dead case.

    The file's ``Dead`` has ``SelfWeightCoefficients`` of (0, 0, -1). Cases
    that check one load against a closed form take it out.
    """
    model = ifcopenshell.open(BEAM)
    if not self_weight:
        for case in model.by_type("IfcStructuralLoadCase"):
            case.SelfWeightCoefficients = None
    return model


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

    @pytest.mark.parametrize("mesh_size", [0.5, 0.25, 0.1])
    def test_clamped_root_does_not_stiffen_it(self, tmp_path, mesh_size):
        """The knot at the root holds its section rigid (aiz.91).

        With the material's Poisson's ratio the section could not contract
        there as bending makes it, and the cantilever was 1.2, 0.75 and
        0.5 % stiff at these meshes. Without it, it was 0.29 % stiff at all
        three until its shear modulus along the depth was made 5/6 of the
        material's (aiz.101); it is now Timoshenko's to 1e-6.
        """
        data = _run(CANTILEVER, tmp_path, mesh_size=mesh_size, gravity=True)
        expected = _cantilever_self_weight(
            self.AREA, 0.2 * 0.4**3 / 12, self.SHEAR_AREA
        )
        assert _max_vertical_deflection(data) == pytest.approx(expected, rel=1e-5)

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

    def test_force_diagram_on_a_coarse_mesh(self, tmp_path):
        """Six elements: the moment is exact at every cross-section.

        The solver's stress is a straight line along each element, through
        the parabola of the moment at two points; read at the ends it was
        w h² / 12 too large, 0.5% of the root moment (``aiz.89``).
        """
        data = _run(CANTILEVER, tmp_path, 0.5, gravity=True)
        diagram = _curve_member_diagram(data)
        load = CANT_RHO * G_ACCEL * 0.2 * 0.4
        root_moment = load * CANT_L**2 / 2
        assert len(diagram["distance_m"]) == 13
        for x, moment in zip(diagram["distance_m"], diagram["Mf1_Nm"]):
            assert moment == pytest.approx(
                load * (CANT_L - x) ** 2 / 2, abs=1e-4 * root_moment
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

        CalculiX reports the force inside the structure at a support node,
        which lacks the share of the weight that lands on the node itself
        (1.4 % here at a 0.25 m mesh). The results add it back.
        """
        data = _run(CANTILEVER, tmp_path, gravity=True)
        weight = CANT_RHO * self.AREA * G_ACCEL * CANT_L
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            weight, rel=1e-4
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

    def test_reaction_holds_up_the_weight(self, tmp_path):
        """CalculiX gives the force at a U1 element's first node the wrong
        sign (aiz.19): the root once pushed down with 2.6 N for 2.7 N."""
        path = _cantilever_variant(tmp_path, i_profile=True)
        data = _run(path, tmp_path, **self.U1)
        weight = CANT_RHO * G_ACCEL * I_AREA * CANT_L
        (support,) = data["supports"]
        assert support["forces"] == "solver"
        assert support["moments"] == "solver"
        (reaction,) = support["by_load_case"].values()
        assert reaction["fz_N"] == pytest.approx(weight, rel=1e-4)
        # The cantilever runs along +x from the root
        assert reaction["my_Nm"] == pytest.approx(-weight * CANT_L / 2, rel=1e-4)

    @pytest.mark.parametrize(
        "axis, moment_key, shear_key, mesh, moment_error, shear_error",
        [
            (None, "Mf1_Nm", "Vf1_N", MESH_SIZE, 2e-4, 0.01),
            ((0.0, 1.0, 0.0), "Mf2_Nm", "Vf2_N", 0.25, 1e-3, 0.01),
        ],
        ids=["strong", "weak"],
    )
    def test_section_forces_follow_the_weight(
        self, tmp_path, axis, moment_key, shear_key, mesh, moment_error, shear_error
    ):
        """w (L - x) and w (L - x)^2 / 2 at every node (bgz).

        U1 elements have no stresses; the weight written on their nodes is
        taken off what each element's stiffness gives. Turned on its side
        the moment is about the section's other axis. The result file has
        six figures, and towards the free end the forces are small
        differences of large displacements: measured, the weak axis's shear
        is out by 0.7% of the root's at a 0.25 m mesh and 5% at 0.05 m, its
        moment by 3e-4 to 1e-3.
        """
        w = CANT_RHO * G_ACCEL * I_AREA
        path = _cantilever_variant(tmp_path, axis=axis, i_profile=True)
        data = _run(path, tmp_path, mesh, **self.U1)
        diagram = _curve_member_diagram(data)
        for x, moment, shear in zip(
            diagram["distance_m"], diagram[moment_key], diagram[shear_key]
        ):
            beyond = CANT_L - x
            assert abs(moment) == pytest.approx(
                w * beyond**2 / 2, abs=moment_error * w * CANT_L**2 / 2
            )
            assert abs(shear) == pytest.approx(w * beyond, abs=shear_error * w * CANT_L)


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
            weight, rel=1e-4
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

    def test_modal_analysis_is_refused(self, tmp_path):
        with pytest.raises(ModelExtractionError, match="no mass density") as raised:
            analyze_ifc(
                ifc_path=self._variant(tmp_path),
                output_dir=str(tmp_path / "out"),
                mesh_size=MESH_SIZE,
                analysis_type="modal",
            )
        assert raised.value.code == "E-MAT-003"


class TestMemberWithoutAxis:
    """cantilever_01 with nothing to say which way its section is turned.

    ``Axis`` runs along the member, which says no more than a missing one
    (IFC2X3 has no such attribute; ifcopenshell will not always take one out
    of an IFC4 file). The section is then placed with its depth as near vertical as the
    member allows, and for a section that is not the same both ways the
    result has to say so.
    """

    MESSAGE = "orientation of their section"

    def _variant(self, tmp_path, circle=False) -> str:
        model = ifcopenshell.open(CANTILEVER)
        member = model.by_type("IfcStructuralCurveMember")[0]
        member.Axis.DirectionRatios = (1.0, 0.0, 0.0)
        if circle:
            model.by_type("IfcMaterialProfile")[0].Profile = model.create_entity(
                "IfcCircleProfileDef",
                ProfileType="AREA",
                ProfileName="benchmark",
                Radius=0.15,
            )
        path = str(tmp_path / "variant.ifc")
        model.write(path)
        return path

    def _warnings(self, ifc_path, tmp_path):
        result = analyze_ifc(
            ifc_path=ifc_path,
            output_dir=str(tmp_path / "out"),
            mesh_size=MESH_SIZE,
            gravity=True,
        )
        assert result["status"] == "success", result.get("errors")
        return [
            w["message"] for w in result["warnings"] if self.MESSAGE in w["message"]
        ]

    def test_rectangle_is_reported(self, tmp_path):
        path = self._variant(tmp_path)
        model = ifcopenshell.open(path)
        guid = model.by_type("IfcStructuralCurveMember")[0].GlobalId
        (message,) = self._warnings(path, tmp_path)
        assert guid in message

    def test_rectangle_is_analysed_with_its_depth_vertical(self, tmp_path):
        data = _run(self._variant(tmp_path), tmp_path, gravity=True)
        expected = _cantilever_self_weight(
            0.2 * 0.4, 0.2 * 0.4**3 / 12, 0.2 * 0.4 * 5 / 6
        )
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )

    def test_circle_is_not_reported(self, tmp_path):
        assert not self._warnings(self._variant(tmp_path, circle=True), tmp_path)

    def test_member_with_an_axis_is_not_reported(self, tmp_path):
        assert not self._warnings(CANTILEVER, tmp_path)


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
            CANT_RHO * G_ACCEL * area * CANT_L, rel=1e-4
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
    """beam_01: 4 m, both ends fully fixed, 0.3 m square, as the file has it.

    Its one load case, ``Dead``, is 20 kN at midspan and the beam's own
    weight (``SelfWeightCoefficients`` of (0, 0, -1)): P and w below.
    """

    LENGTH = 4.0
    LOAD = 20000.0
    E = 3.0e10
    NU = 0.2
    AREA = 0.3 * 0.3
    INERTIA = 0.3**4 / 12
    DENSITY = 2500.0
    WEIGHT = DENSITY * AREA * G_ACCEL  # per metre

    def test_midspan_deflection(self, tmp_path):
        data = _run(BEAM, tmp_path)
        shear_stiffness = self.E / (2 * (1 + self.NU)) * self.AREA * 5 / 6
        bending_stiffness = self.E * self.INERTIA
        expected = (
            self.LOAD * self.LENGTH**3 / (192 * bending_stiffness)
            + self.LOAD * self.LENGTH / (4 * shear_stiffness)
            + self.WEIGHT * self.LENGTH**4 / (384 * bending_stiffness)
            + self.WEIGHT * self.LENGTH**2 / (8 * shear_stiffness)
        )
        # 1 % stiff until the shear modulus of solid rectangles was put
        # right (aiz.101); exact to 1e-5 now
        assert _max_vertical_deflection(data) == pytest.approx(expected, rel=2e-3)

    def test_section_forces(self, tmp_path):
        """Largest at the ends: shear (P + w L) / 2, moment P L / 8 + w L^2 / 12."""
        data = _run(BEAM, tmp_path)
        forces = _curve_member_envelope(data)["section_forces"]
        assert forces["max_Vf1_N"] == pytest.approx(
            (self.LOAD + self.WEIGHT * self.LENGTH) / 2, rel=FORCE_TOLERANCE
        )
        assert forces["max_Mf1_Nm"] == pytest.approx(
            self.LOAD * self.LENGTH / 8 + self.WEIGHT * self.LENGTH**2 / 12,
            rel=FORCE_TOLERANCE,
        )

    def test_shear_steps_under_the_load(self, tmp_path):
        """The shear jumps by P at midspan, where both sides are listed.

        Before it the shear is -P/2 less the weight between there and
        midspan, and after it +P/2 plus the same.

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
                assert shear == pytest.approx(
                    sign * half + self.WEIGHT * (x - self.LENGTH / 2),
                    rel=FORCE_TOLERANCE,
                )
        # Hogging at the supports, sagging under the load
        hogging = self.LOAD * self.LENGTH / 8 + self.WEIGHT * self.LENGTH**2 / 12
        sagging = self.LOAD * self.LENGTH / 8 + self.WEIGHT * self.LENGTH**2 / 24
        assert diagram["Mf1_Nm"][0] == pytest.approx(hogging, rel=FORCE_TOLERANCE)
        assert diagram["Mf1_Nm"][at_load[0]] == pytest.approx(
            -sagging, rel=FORCE_TOLERANCE
        )
        assert diagram["Mf1_Nm"][-1] == pytest.approx(hogging, rel=FORCE_TOLERANCE)

    def test_reaction_equals_applied_load(self, tmp_path):
        data = _run(BEAM, tmp_path)
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            self.LOAD + self.WEIGHT * self.LENGTH, rel=1e-6
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
    model = _beam_01()
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
        # 4e-4 (1 % stiff before aiz.101)
        assert envelope["max_tz_m"] == pytest.approx(self._expected(), rel=2e-3)
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
        model = _beam_01()
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
        # 6e-4 (0.2 % stiff before aiz.101)
        assert _max_vertical_deflection(data) == pytest.approx(expected, rel=2e-3)
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

    def test_line_load_on_user_elements(self, tmp_path):
        """w x (L - x) / 2 at every node, the shear w (L / 2 - x) (bgz).

        The beam is statically determinate, so the section forces worked out
        from the stiffness of U1 elements are those of statics at every node
        whatever the mesh, once each element's share of the load is taken
        off what its nodes put on it.
        """
        path = _beam_on_supports(
            tmp_path, PIN, ROLLER, line_load=self.LINE_LOAD, i_profile=True
        )
        data = _run(path, tmp_path, self.MESH, open_sections="user_element")
        diagram = _curve_member_diagram(data)
        load, length = self.LINE_LOAD, self.B.LENGTH
        largest = load * length**2 / 8
        for x, moment, shear in zip(
            diagram["distance_m"], diagram["Mf1_Nm"], diagram["Vf1_N"]
        ):
            # Sagging: the fibres below, on the -1 side, in tension
            assert -moment == pytest.approx(
                load * x * (length - x) / 2, abs=1e-3 * largest
            )
            assert abs(shear) == pytest.approx(
                abs(load * (length / 2 - x)), abs=1e-3 * load * length
            )
        forces = _curve_member_envelope(data)["section_forces"]
        assert forces["max_Mf1_Nm"] == pytest.approx(largest, rel=1e-3)

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
            CANT_RHO * G_ACCEL * area * CANT_L, rel=1e-4
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

    @pytest.mark.parametrize("mesh_size", [0.25, MESH_SIZE])
    def test_point_load(self, tmp_path, mesh_size):
        """Timoshenko's beam at any mesh.

        The load once dented the equivalent rectangle's corners, 1.2 % at a
        0.25 m mesh and 3.1 % at 0.05 m, and the knots at the clamped ends
        stiffened it back by part of that (aiz.91): the node under the load
        is a knot now, and beams have no Poisson's ratio.
        """
        model = _beam_01()
        _give_beam_01_an_i_profile(model)
        path = str(tmp_path / "i_beam.ifc")
        model.write(path)
        data = _run(path, tmp_path, mesh_size=mesh_size)
        bending, shear = self._stiffness()
        expected = self.B.LOAD * self.B.LENGTH**3 / (
            192 * bending
        ) + self.B.LOAD * self.B.LENGTH / (4 * shear)
        assert _max_vertical_deflection(data) == pytest.approx(expected, rel=1e-3)
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            self.B.LOAD, rel=1e-3
        )

    def test_point_load_on_user_elements(self, tmp_path):
        """Each clamped end of a U1 beam takes half the load and PL/8.

        The total of the solver's forces was once zero (aiz.19). The forces
        are worked out from the elements' stiffness and displacements read
        to six figures, which the shear of a short element loses some of.
        """
        model = _beam_01()
        _give_beam_01_an_i_profile(model)
        path = str(tmp_path / "i_beam.ifc")
        model.write(path)
        data = _run(path, tmp_path, open_sections="user_element")
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            self.B.LOAD, rel=1e-3
        )
        moments = []
        for support in data["supports"]:
            assert support["forces"] == "solver"
            assert support["moments"] == "solver"
            (reaction,) = support["by_load_case"].values()
            assert reaction["fz_N"] == pytest.approx(self.B.LOAD / 2, rel=1e-3)
            moments.append(reaction["my_Nm"])
        assert sorted(moments) == pytest.approx(
            [-self.B.LOAD * self.B.LENGTH / 8, self.B.LOAD * self.B.LENGTH / 8],
            rel=0.01,
        )

    def test_section_forces_of_user_elements(self, tmp_path):
        """PL/8 at the ends and in the middle, and the shear steps by P (bgz).

        U1 elements have no stresses; their section forces are worked out
        from their stiffness. The jump under the load is one-sided at once.
        """
        model = _beam_01()
        _give_beam_01_an_i_profile(model)
        path = str(tmp_path / "i_beam.ifc")
        model.write(path)
        data = _run(path, tmp_path, open_sections="user_element")
        diagram = _curve_member_diagram(data)
        load, length = self.B.LOAD, self.B.LENGTH
        moments = diagram["Mf1_Nm"]
        middle = min(
            range(len(moments)),
            key=lambda i: abs(diagram["distance_m"][i] - length / 2),
        )
        for value in (moments[0], moments[-1], -moments[middle]):
            assert value == pytest.approx(load * length / 8, rel=0.01)
        shears = diagram["Vf1_N"]
        assert max(shears) - min(shears) == pytest.approx(load, rel=1e-3)
        assert abs(shears[0]) == pytest.approx(load / 2, rel=1e-3)
        forces = _curve_member_envelope(data)
        assert forces["section_forces"]["max_Mf1_Nm"] == pytest.approx(
            load * length / 8, rel=0.01
        )
        assert forces["max_normal_stress_Pa"] == pytest.approx(
            load * length / 8 / I_STRONG * I_H / 2, rel=0.01
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
        # Half each, and the weight's moment about the roots. A beam tied to
        # the slab has only its share of the force at its end: that was once
        # taken to show the solver wrong, and each root given 58.5 N of 49.7
        _needs_solver_reactions()
        for support in data["supports"]:
            assert support["forces"] == "solver"
            assert support["moments"] == "solver"
            reaction = support["by_load_case"]["Gravity"]
            assert reaction["fz_N"] == pytest.approx(weight / 2, rel=1e-3)
            assert reaction["my_Nm"] == pytest.approx(-weight * SOB_L / 4, rel=1e-3)

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

    def test_results_say_which_members_were_tied(self, tmp_path):
        """A tied member's section forces are its share only (`aiz.86`)."""
        path = _slab_on_two_cantilevers(tmp_path, inset=0.25)
        result = analyze_ifc(
            ifc_path=path,
            output_dir=str(tmp_path / "out"),
            mesh_size=self.MESH,
            gravity=True,
        )
        assert result["status"] == "success", result.get("errors")
        assert any(
            "depend on the mesh size" in w["message"] for w in result["warnings"]
        )
        with open(os.path.join(str(tmp_path / "out"), "results.json")) as fh:
            members = json.load(fh)["members"]
        (slab,) = [m for m in members if m["type"] == "surface"]
        assert "tied_to_surface_members" not in slab
        beams = [m for m in members if m["type"] == "curve"]
        assert len(beams) == 2
        for beam in beams:
            assert beam["tied_to_surface_members"] == [slab["id"]]

        result = analyze_ifc(
            ifc_path=path,
            output_dir=str(tmp_path / "strict"),
            mesh_size=self.MESH,
            gravity=True,
            strict_connections=True,
        )
        with open(os.path.join(str(tmp_path / "strict"), "results.json")) as fh:
            members = json.load(fh)["members"]
        assert not [m for m in members if "tied_to_surface_members" in m]

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
        _needs_solver_reactions()
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


def _needs_solver_reactions() -> None:
    if not solver_reports_clamped_reactions():
        pytest.skip(
            "this CalculiX misreports reactions at supports that hold a rotation"
        )


# Where the moments of a support that holds a rotation come from: the
# solver's forces on the nodes it was expanded into, or, where the solver got
# those wrong at a clamped member end (CalculiX 2.21), the ends of its members
MOMENT_SOURCES = ("solver", "member_end_forces")


def _support_at(data: dict, position) -> dict:
    """The support of a results file nearest a point."""
    return min(
        data["supports"],
        key=lambda s: sum((a - b) ** 2 for a, b in zip(s["position_m"], position)),
    )


class TestSupportReactions:
    """The reaction at each support, against statics (`94g.1`).

    Forces are the solver's. It gives a node no moment: those are the
    moments of its forces on the nodes the support's own were expanded into
    (`94g.8`), or the section forces at the ends of the members a support
    holds where the solver got its forces wrong.
    """

    def test_cantilever_root(self, tmp_path):
        """Weight upwards and w L^2 / 2 against the sag."""
        data = _run(CANTILEVER, tmp_path, gravity=True)
        (support,) = data["supports"]
        weight = CANT_RHO * G_ACCEL * 0.2 * 0.4 * CANT_L
        assert support["type"] == "point"
        assert support["restrained"] == ["tx", "ty", "tz", "rx", "ry", "rz"]
        exact = solver_reports_clamped_reactions()
        assert support["moments"] == ("solver" if exact else "member_end_forces")
        reaction = support["by_load_case"]["Gravity"]
        assert reaction["fz_N"] == pytest.approx(weight, rel=FORCE_TOLERANCE)
        # The solver's forces are in equilibrium; integrated stresses are near
        assert reaction["my_Nm"] == pytest.approx(
            -weight * CANT_L / 2, rel=1e-4 if exact else FORCE_TOLERANCE
        )
        for key in ("fx_N", "fy_N"):
            assert abs(reaction[key]) < 1e-3 * weight
        for key in ("mx_Nm", "mz_Nm"):
            assert abs(reaction[key]) < 1e-3 * weight * CANT_L

    def test_fixed_fixed_beam(self, tmp_path):
        """Half the load and weight at each end, and the fixing moments.

        P L / 8 + w L^2 / 12, turning opposite ways.
        """
        beam = TestFixedFixedBeamPointLoad
        data = _run(BEAM, tmp_path)
        left = _support_at(data, (0.0, 4.0, 4.0))
        right = _support_at(data, (beam.LENGTH, 4.0, 4.0))
        assert left["id"] != right["id"]
        force = (beam.LOAD + beam.WEIGHT * beam.LENGTH) / 2
        moment = beam.LOAD * beam.LENGTH / 8 + beam.WEIGHT * beam.LENGTH**2 / 12
        for support, sign in ((left, -1.0), (right, 1.0)):
            (reaction,) = support["by_load_case"].values()
            assert reaction["fz_N"] == pytest.approx(force, rel=FORCE_TOLERANCE)
            assert reaction["my_Nm"] == pytest.approx(
                sign * moment, rel=FORCE_TOLERANCE
            )
            assert reaction["resultant_N"] == pytest.approx(force, rel=FORCE_TOLERANCE)

    def test_member_ends_have_the_support_moments(self, tmp_path):
        """The moments at the ends of beam_01's diagram are those the solver's
        nodal forces give its supports. They were 46 N·m apart at a 0.5 m
        mesh, w h² / 12 (``aiz.89``)."""
        _needs_solver_reactions()
        beam = TestFixedFixedBeamPointLoad
        data = _run(BEAM, tmp_path, 0.5)
        diagram = _curve_member_diagram(data)
        left = _support_at(data, (0.0, 4.0, 4.0))
        right = _support_at(data, (beam.LENGTH, 4.0, 4.0))
        for support, end in ((left, 0), (right, -1)):
            assert support["moments"] == "solver"
            (reaction,) = support["by_load_case"].values()
            assert abs(diagram["Mf1_Nm"][end]) == pytest.approx(
                abs(reaction["my_Nm"]), rel=1e-4
            )

    def test_pin_and_roller_carry_no_bending_moment(self, tmp_path):
        """w L / 2 each. The pin's hold on the beam's own axis carries nothing."""
        line_load = 5000.0
        path = _beam_on_supports(tmp_path, PIN, ROLLER, line_load=line_load)
        data = _run(path, tmp_path, 0.25)
        length = TestFixedFixedBeamPointLoad.LENGTH
        assert len(data["supports"]) == 2
        for support in data["supports"]:
            (reaction,) = support["by_load_case"].values()
            assert reaction["fz_N"] == pytest.approx(line_load * length / 2, rel=1e-6)
            for key in ("mx_Nm", "my_Nm", "mz_Nm"):
                assert abs(reaction[key]) < 1e-3 * line_load * length**2 / 8
        roller = _support_at(data, (length, 4.0, 4.0))
        assert "tx" not in roller["restrained"]

    def test_load_on_a_support_goes_into_its_reaction(self, tmp_path):
        """A quarter of a line load's end element lands on the support node.

        The solver's own total at a 1 m mesh is short by w / 3 (two end
        nodes, a sixth of an element each).
        """
        line_load = 5000.0
        path = _beam_on_supports(tmp_path, PIN, ROLLER, line_load=line_load)
        data = _run(path, tmp_path, 1.0)
        length = TestFixedFixedBeamPointLoad.LENGTH
        (total,) = data["global_reactions"]["by_load_case"].values()
        assert total["fz_N"] == pytest.approx(line_load * length, rel=1e-6)

    def test_bending_and_torque_at_one_root(self, tmp_path):
        """A load off the member's line: the root moment is -(r x F) in full."""
        path = _balcony_frame(
            tmp_path, "IfcRectangleProfileDef", {"XDim": 0.3, "YDim": 0.3}
        )
        data = _run(path, tmp_path, mesh_size=0.125)
        (support,) = data["supports"]
        (reaction,) = support["by_load_case"].values()
        assert reaction["fz_N"] == pytest.approx(TORSION_P, rel=FORCE_TOLERANCE)
        assert reaction["mx_Nm"] == pytest.approx(
            TORSION_P * TORSION_LB, rel=FORCE_TOLERANCE
        )
        assert reaction["my_Nm"] == pytest.approx(
            -TORSION_P * TORSION_LA, rel=FORCE_TOLERANCE
        )
        assert abs(reaction["mz_Nm"]) < 1e-3 * TORSION_P * TORSION_LA

    @pytest.mark.parametrize(
        "name, mesh, gravity",
        [
            ("portal_01", 0.25, False),
            ("structure_01", 0.5, True),
            ("slab_01", 0.25, True),
            ("grid_of_beams", 0.25, True),
            ("building_01", 1.0, False),
        ],
    )
    def test_supports_add_up_to_the_whole(self, tmp_path, name, mesh, gravity):
        """Every force the solver reports is given to one support."""
        _needs_solver_reactions()
        data = _run(
            os.path.join(IFC_DIR, f"{name}.ifc"), tmp_path, mesh, gravity=gravity
        )
        assert data["supports"]
        for case, total in data["global_reactions"]["by_load_case"].items():
            scale = max(abs(total[key]) for key in ("fx_N", "fy_N", "fz_N"))
            for key in ("fx_N", "fy_N", "fz_N"):
                summed = sum(s["by_load_case"][case][key] for s in data["supports"])
                assert summed == pytest.approx(total[key], abs=1e-6 * scale)
            # and their moments about the origin balance those of the loads
            turning = max(abs(v) for v in total["applied_moment_Nm"])
            assert turning > scale
            assert total["moment_imbalance_Nm"] < 1e-5 * turning
            for key, applied in zip(
                ("mx_Nm", "my_Nm", "mz_Nm"), total["applied_moment_Nm"]
            ):
                assert total[key] == pytest.approx(-applied, abs=1e-5 * turning)

    def test_portal_feet_balance_its_load(self, tmp_path):
        """portal_01 is loaded on the right half of its beam only.

        Equal and opposite thrusts, and moments about the left foot: the
        load acts three quarters of the way across.
        """
        data = _run(os.path.join(IFC_DIR, "portal_01.ifc"), tmp_path, 0.25)
        left, right = sorted(data["supports"], key=lambda s: s["position_m"][0])
        (a,), (b,) = left["by_load_case"].values(), right["by_load_case"].values()
        assert a["fx_N"] == pytest.approx(-b["fx_N"], rel=1e-3)
        assert a["fx_N"] > 0  # the feet are pushed inwards
        assert b["fz_N"] > 3 * a["fz_N"]
        span = right["position_m"][0] - left["position_m"][0]
        load = a["fz_N"] + b["fz_N"]
        assert a["my_Nm"] + b["my_Nm"] - span * b["fz_N"] + load * 0.75 * span == (
            pytest.approx(0.0, abs=FORCE_TOLERANCE * load * span)
        )

    def test_members_that_run_on_past_their_supports(self, tmp_path):
        """grid_of_beams: the main beams run 0.1 m past their supports.

        A member's end forces are then not the support's, and the moments
        were once left out. The grid is the same seen from either side, so
        the four supports hold the same moments, turning opposite ways.
        """
        data = _run(
            os.path.join(IFC_DIR, "grid_of_beams.ifc"), tmp_path, 0.25, gravity=True
        )
        assert len(data["supports"]) == 4
        first = data["supports"][0]["by_load_case"]["Gravity"]
        assert abs(first["my_Nm"]) > 0.5 * first["fz_N"]
        for support in data["supports"]:
            assert support["moments"] == "solver"
            reaction = support["by_load_case"]["Gravity"]
            assert reaction["fz_N"] > 0
            for key in ("mx_Nm", "my_Nm", "mz_Nm"):
                assert abs(reaction[key]) == pytest.approx(abs(first[key]), rel=1e-3)
        for key in ("mx_Nm", "my_Nm", "mz_Nm"):
            total = sum(s["by_load_case"]["Gravity"][key] for s in data["supports"])
            assert abs(total) < 1e-3 * abs(first["my_Nm"])

    def test_point_load_on_a_clamped_support(self, tmp_path):
        """A load on the very node a cantilever is clamped at (`94g.7`).

        It goes into the support and the member has none of it. The member's
        end was once taken to show the solver wrong by that load, and the
        reaction given was the member's, 700 N short and with no thrust.
        """
        data, warnings = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (4, 0)},
            members=[("A", "B")],
            supports={"A": PLANE_FIXED},
            loads={"A": (300.0, -700.0), "B": (0.0, -1000.0)},
            hinged=False,
            mesh_size=0.25,
        )
        (support,) = data["supports"]
        reaction = support["by_load_case"]["Load"]
        assert reaction["fx_N"] == pytest.approx(-300.0, rel=1e-3)
        assert reaction["fz_N"] == pytest.approx(1700.0, rel=1e-3)
        assert reaction["my_Nm"] == pytest.approx(-4000.0, rel=1e-3)
        total = data["global_reactions"]["total"]
        assert total["imbalance_N"] < 1e-3 * 1700.0
        if solver_reports_clamped_reactions():
            assert support["forces"] == "solver"
            assert not [w for w in warnings if "solver reported" in w]

    def test_member_clamped_along_its_span(self, tmp_path):
        """A bar held at one point, 1 m from one end and 2 m from the other.

        It runs on past the support both ways, so no member ends there.
        Statics gives the reaction: the loads at the two ends, and their
        moments about the support.
        """
        data, _ = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (1, 0), "C": (3, 0)},
            members=[("A", "C")],
            supports={"B": PLANE_FIXED},
            loads={"A": (0.0, -1000.0), "C": (500.0, -3000.0)},
            hinged=False,
            mesh_size=0.25,
        )
        (support,) = data["supports"]
        assert support["moments"] == "solver"
        reaction = support["by_load_case"]["Load"]
        assert reaction["fx_N"] == pytest.approx(-500.0, rel=1e-4)
        assert reaction["fz_N"] == pytest.approx(4000.0, rel=1e-4)
        assert reaction["my_Nm"] == pytest.approx(1000.0 - 2 * 3000.0, rel=1e-4)
        for key in ("mx_Nm", "mz_Nm"):
            assert abs(reaction[key]) < 1e-3 * abs(reaction["my_Nm"])

    @pytest.mark.parametrize("mesh_size", [1.0, 0.5])
    def test_slab_clamped_along_one_edge(self, tmp_path, mesh_size):
        """slab_01 as a cantilever, 5 m out from its edge at x = 0, 3 m wide.

        Under 2 kN/m2 the edge takes the load and its moment about itself,
        q b a^2 / 2, at any mesh size: these are the solver's own forces. At
        1 m they are couples of 50 kN through the thickness at each node,
        written with six figures, and still have to be recognised as adding
        up to the node's force.
        """
        pressure, a, b = 2000.0, 5.0, 3.0
        path = _slab_variant(
            tmp_path,
            edge_conditions=(
                (True, True, True, True, False, False),
                (False, False, False, False, False, False),
            ),
            area_load=(0.0, 0.0, -pressure),
        )
        data = _run(path, tmp_path, mesh_size=mesh_size)
        (support,) = data["supports"]
        assert support["type"] == "line"
        assert support["restrained"] == ["tx", "ty", "tz", "ry"]
        assert support["moments"] == "solver"
        reaction = support["by_load_case"]["Imposed"]
        load = pressure * a * b
        assert reaction["fz_N"] == pytest.approx(load, rel=1e-4)
        assert reaction["my_Nm"] == pytest.approx(-load * a / 2, rel=1e-4)
        for key in ("mx_Nm", "mz_Nm"):
            assert abs(reaction[key]) < 1e-3 * abs(reaction["my_Nm"])
        assert support["by_load_case_in_axes"]["Imposed"]["mx_Nm"] == pytest.approx(
            -load * a / 2, rel=1e-4
        )

    def test_line_support_in_its_own_axes(self, tmp_path):
        """structure_01's wall foot: x along the edge, the lift along its y."""
        data = _run(
            os.path.join(IFC_DIR, "structure_01.ifc"), tmp_path, 0.5, gravity=True
        )
        (line,) = [s for s in data["supports"] if s["type"] == "line"]
        assert line["position_m"] == pytest.approx([5.0, 2.0, 0.0])
        assert [abs(v) for v in line["axes"]["x"]] == pytest.approx([0.0, 1.0, 0.0])
        globally = line["by_load_case"]["Gravity"]
        locally = line["by_load_case_in_axes"]["Gravity"]
        for name, row in line["axes"].items():
            expected = sum(
                component * globally[key]
                for component, key in zip(row, ("fx_N", "fy_N", "fz_N"))
            )
            assert locally[f"f{name}_N"] == pytest.approx(expected)
        assert globally["fz_N"] > 0.5 * data["global_reactions"]["total"]["fz_N"]


POUND_FORCE = 4.4482216152605
INCH = 0.0254


def _portal_reactions_in_the_file() -> dict:
    """The reactions portal_01.ifc holds for its own load case.

    Returns:
        ``{x of the foot in m: (fx, my, fz)}`` in N and N·m.
    """
    reactions = {}
    model = ifcopenshell.open(os.path.join(IFC_DIR, "portal_01.ifc"))
    for reaction in model.by_type("IfcStructuralPointReaction"):
        result = reaction.AppliedLoad
        if not result.is_a("IfcStructuralLoadSingleForce"):
            continue  # the displacement of the same node
        (relation,) = reaction.AssignedToStructuralItem
        (vertex,) = relation.RelatingElement.Representation.Representations[0].Items
        reactions[round(vertex.VertexGeometry.Coordinates[0] * INCH, 3)] = (
            result.ForceX * POUND_FORCE,
            result.MomentY * POUND_FORCE * INCH,
            result.ForceZ * POUND_FORCE,
        )
    return reactions


class TestAreaInAUnitOfItsOwn:
    """A profile's ``CrossSectionArea`` is in the file's AREAUNIT (``94g.22``).

    Bonsai's default project has lengths in millimetres and areas in square
    metres. The area was scaled by the length unit squared: a HEB 160 came out
    with 5.4e-9 m2, a 231 m deep equivalent rectangle, and 1.14 m of displacement
    on its faces under a load that bends it 13.6 mm. portal_01 is the one example
    with a mechanical profile pset; here it gives its area in square metres.
    """

    SHIPPED = os.path.join(IFC_DIR, "portal_01.ifc")

    def _in_square_metres(self, tmp_path) -> str:
        model = ifcopenshell.open(self.SHIPPED)
        (assignment,) = model.by_type("IfcUnitAssignment")
        assignment.Units = [
            unit
            for unit in assignment.Units
            if getattr(unit, "UnitType", None) != "AREAUNIT"
        ] + [model.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")]
        for pset in model.by_type("IfcProfileProperties"):
            for prop in pset.Properties:
                if prop.Name == "CrossSectionArea":
                    prop.NominalValue.wrappedValue *= INCH**2
        path = str(tmp_path / "square_metres.ifc")
        model.write(path)
        return path

    def test_same_section(self, tmp_path):
        shipped = Extractor(self.SHIPPED).extract_model().members[0].section
        restated = (
            Extractor(self._in_square_metres(tmp_path))
            .extract_model()
            .members[0]
            .section
        )
        assert restated.area == pytest.approx(8.84 * INCH**2, rel=1e-9)
        assert restated.area == pytest.approx(shipped.area, rel=1e-3)

    def test_same_results(self, tmp_path):
        """On the faces too, where a section of the wrong depth shows."""
        shipped = _run(self.SHIPPED, tmp_path / "shipped", 0.5)
        restated = _run(self._in_square_metres(tmp_path), tmp_path / "restated", 0.5)
        for ours, theirs in zip(restated["members"], shipped["members"]):
            assert ours["envelope"]["max_displacement_m"] == pytest.approx(
                theirs["envelope"]["max_displacement_m"], rel=1e-3
            )


class TestStatedProfileValues:
    """What Pset_ProfileMechanical states reaches the solver (``94g.24``).

    The inertias were read and dropped, the area kept: a HEB 160 was analysed
    with 2.414e-5 m4 for the 2.494e-5 of its tables.
    """

    def test_cantilever_bends_with_the_stated_section(self, tmp_path):
        area, strong = 1.1 * I_AREA, 1.2 * I_STRONG
        path = _cantilever_variant(tmp_path, i_profile=True)
        model = ifcopenshell.open(path)
        (profile,) = model.by_type("IfcIShapeProfileDef")
        model.create_entity(
            "IfcProfileProperties",
            Name="Pset_ProfileMechanical",
            Properties=[
                model.create_entity(
                    "IfcPropertySingleValue",
                    Name=name,
                    NominalValue=model.create_entity(measure, value),
                )
                for name, measure, value in (
                    ("CrossSectionArea", "IfcAreaMeasure", area),
                    ("MomentOfInertiaY", "IfcMomentOfInertiaMeasure", strong),
                )
            ],
            ProfileDefinition=profile,
        )
        model.write(path)
        data = _run(path, tmp_path, gravity=True)
        assert _max_vertical_deflection(data) == pytest.approx(
            _cantilever_self_weight(area, strong, I_H * I_TW), rel=DEFLECTION_TOLERANCE
        )


class TestDensityWithNoUnit:
    """A density with no MASSDENSITYUNIT is in kg/m3, as in Bonsai (``94g.23``).

    In a file in millimetres it was once divided by the length unit cubed, and
    a member came out a billion times too heavy.
    """

    def test_weighs_the_same(self, tmp_path):
        model = ifcopenshell.open(BEAM)
        (assignment,) = model.by_type("IfcUnitAssignment")
        assignment.Units = [
            unit
            for unit in assignment.Units
            if getattr(unit, "UnitType", None) != "MASSDENSITYUNIT"
        ]
        for prop in model.by_type("IfcPropertySingleValue"):
            if prop.Name == "MassDensity":
                prop.NominalValue.wrappedValue = 2500.0
                prop.Unit = None
        path = str(tmp_path / "no_density_unit.ifc")
        model.write(path)
        restated = _run(path, tmp_path / "restated", 0.5)
        shipped = _run(BEAM, tmp_path / "shipped", 0.5)
        for name, ours in restated["global_reactions"]["by_load_case"].items():
            theirs = shipped["global_reactions"]["by_load_case"][name]
            assert ours["fz_N"] == pytest.approx(theirs["fz_N"], rel=1e-6)


class TestDeclaredUnits:
    """Loads and moduli restated in other units give the same results (``94g.25``).

    A derived unit need not be made of the file's length and force units.
    ``portal_01`` is in pounds and inches: here its line load is in kN/m and
    its moduli in GPa, whichever way they are declared.
    """

    @staticmethod
    def _restated(tmp_path, own_units: bool) -> str:
        model = ifcopenshell.open(os.path.join(IFC_DIR, "portal_01.ifc"))
        kilonewton = model.create_entity(
            "IfcSIUnit", UnitType="FORCEUNIT", Prefix="KILO", Name="NEWTON"
        )
        metre = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")

        def derived(unit_type, *elements):
            return model.create_entity(
                "IfcDerivedUnit",
                Elements=[
                    model.create_entity(
                        "IfcDerivedUnitElement", Unit=unit, Exponent=exponent
                    )
                    for unit, exponent in elements
                ],
                UnitType=unit_type,
            )

        gigapascal = model.create_entity(
            "IfcSIUnit", UnitType="PRESSUREUNIT", Prefix="GIGA", Name="PASCAL"
        )
        declared = [
            derived("LINEARFORCEUNIT", (kilonewton, 1), (metre, -1)),
            derived("MODULUSOFELASTICITYUNIT", (gigapascal, 1)),
            derived("SHEARMODULUSUNIT", (gigapascal, 1)),
        ]
        moduli = {prop.UnitType: prop for prop in declared[1:]}
        (assignment,) = model.by_type("IfcUnitAssignment")
        replaced = {"LINEARFORCEUNIT"}
        if not own_units:
            replaced |= set(moduli)
        assignment.Units = [
            unit
            for unit in assignment.Units
            if getattr(unit, "UnitType", None) not in replaced
        ] + [unit for unit in declared if unit.UnitType in replaced]

        lbf_per_inch = 4.44822162 / 0.0254
        for load in model.by_type("IfcStructuralLoadLinearForce"):
            load.LinearForceZ = load.LinearForceZ * lbf_per_inch / 1000.0
        psi_in_gpa = 6894.7572932 / 1e9
        for prop in model.by_type("IfcPropertySingleValue"):
            if prop.Name in ("YoungModulus", "ShearModulus"):
                prop.NominalValue.wrappedValue *= psi_in_gpa
                if own_units:
                    prop.Unit = moduli[
                        (
                            "MODULUSOFELASTICITYUNIT"
                            if prop.Name == "YoungModulus"
                            else "SHEARMODULUSUNIT"
                        )
                    ]
        path = str(tmp_path / f"restated_{own_units}.ifc")
        model.write(path)
        return path

    @pytest.mark.parametrize("own_units", [False, True], ids=["project", "property"])
    def test_same_results(self, tmp_path, own_units):
        restated = _run(self._restated(tmp_path, own_units), tmp_path / "restated", 0.5)
        shipped = _run(
            os.path.join(IFC_DIR, "portal_01.ifc"), tmp_path / "shipped", 0.5
        )
        for name, ours in restated["global_reactions"]["by_load_case"].items():
            theirs = shipped["global_reactions"]["by_load_case"][name]
            assert theirs["fz_N"] > 0
            assert ours["fz_N"] == pytest.approx(theirs["fz_N"], rel=1e-5)
        assert restated["global_displacements"]["envelope"][
            "max_displacement_m"
        ] == pytest.approx(
            shipped["global_displacements"]["envelope"]["max_displacement_m"], rel=1e-5
        )


class TestPortalAgainstTheResultsInItsFile:
    """portal_01: 100 lbf/in on the right half of the beam of a W10X30 portal.

    The load is an ``IfcStructuralCurveAction`` whose two values are at 96
    and 192 in along the 192 in beam. Their locations were ignored and the
    load put on the whole beam: 19 200 lbf for 9600, shared equally by the
    feet (``aiz.58``). The file also holds the results of the program that
    wrote it, which nothing compared with ours.

    Its vertical reactions are ours. Its thrust is 1422.7 lbf, which a plane
    frame with shear deformation gives for a shear area of 0.79 of the
    section; with the area of the web, which is what this library takes for
    an I section, the same frame gives 1386.4 lbf, and without shear
    deformation 1454.9.
    """

    THRUST_WITH_THE_SHEAR_AREA_OF_THE_WEB = 1386.37 * POUND_FORCE

    def test_reactions(self, tmp_path):
        _needs_solver_reactions()
        data = _run(os.path.join(IFC_DIR, "portal_01.ifc"), tmp_path, 0.25)
        expected = _portal_reactions_in_the_file()
        assert sorted(expected) == [0.0, 4.877]
        for x, (thrust, moment, lift) in expected.items():
            (reaction,) = _support_at(data, (x, 0.0, 0.0))["by_load_case"].values()
            assert reaction["fz_N"] == pytest.approx(lift, rel=1e-3)
            sign = 1.0 if thrust > 0 else -1.0
            assert reaction["fx_N"] == pytest.approx(
                sign * self.THRUST_WITH_THE_SHEAR_AREA_OF_THE_WEB, rel=0.01
            )
            # The shear area the other program took: 2 % in the thrust, and
            # three times that in the moment at a foot, a difference of two
            # larger ones
            assert reaction["fx_N"] == pytest.approx(thrust, rel=0.03)
            assert reaction["my_Nm"] == pytest.approx(moment, rel=0.08)

    def test_user_elements_deflect_as_the_native_beams(self, tmp_path):
        """A U1 member split into two-node elements once had no node at its
        end, and a model with joints between U1 members did not run."""
        path = os.path.join(IFC_DIR, "portal_01.ifc")
        (tmp_path / "native").mkdir()
        (tmp_path / "u1").mkdir()
        native = _run(path, tmp_path / "native", 0.25)
        u1 = _run(path, tmp_path / "u1", 0.25, open_sections="user_element")
        assert u1["global_displacements"]["envelope"][
            "max_displacement_m"
        ] == pytest.approx(
            native["global_displacements"]["envelope"]["max_displacement_m"],
            rel=0.01,
        )
        # Their reactions once had the wrong sign and added up to -85 kN for
        # 43 kN (aiz.19); the two elements differ by about 0.5 %
        (total,) = u1["global_reactions"]["by_load_case"].values()
        assert total["imbalance_N"] < 1e-4 * abs(total["fz_N"])
        for ours, theirs in zip(u1["supports"], native["supports"]):
            assert ours["position_m"] == theirs["position_m"]
            assert ours["moments"] == "solver"
            (mine,) = ours["by_load_case"].values()
            (other,) = theirs["by_load_case"].values()
            for key in ("fx_N", "fz_N", "my_Nm"):
                assert mine[key] == pytest.approx(other[key], rel=0.01)

    def test_load_is_what_the_file_says(self, tmp_path):
        data = _run(os.path.join(IFC_DIR, "portal_01.ifc"), tmp_path, 0.25)
        (total,) = data["global_reactions"]["by_load_case"].values()
        assert total["applied_load_N"] == pytest.approx(
            [0.0, 0.0, -9600.0 * POUND_FORCE], abs=0.1
        )


class TestLoadThatVariesAlongABeam:
    """A 4 m simply supported beam, 0.1 m square, under loads that vary.

    These were applied as constant loads of their mean value over the whole
    member, with a warning: the right total in the wrong place.
    """

    PEAK, SPAN, SIDE = 3000.0, 4.0, 0.1

    def _beam(self, tmp_path, **line_load):
        data, warnings = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (4, 0)},
            members=[("A", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            loads={},
            hinged=False,
            mesh_size=0.25,
            line_loads={("A", "B"): line_load},
        )
        assert not [w for w in warnings if "varies along its member" in w]
        assert not [w for w in warnings if "nearest mesh node" in w]
        lifts = [
            _support_at(data, (x, 0.0, 0.0))["by_load_case"]["Load"]["fz_N"]
            for x in (0.0, self.SPAN)
        ]
        (member,) = data["members"]
        return data, lifts, member["envelope"]["section_forces"]

    def _assert_shear(self, data, shear, largest):
        """The shear diagram is ``shear(x)`` all along, with no step in it.

        A step was once put at every element end whose load was not that of
        the middle of the beam, 5 to 14% of the shear to either side
        (``aiz.84``).
        """
        (member,) = data["members"]
        diagram = member["section_force_diagrams"]["Load"]
        distances = diagram["distance_m"]
        assert len(distances) == len(set(distances)) > 30
        assert [abs(v) for v in diagram["Vf2_N"]] == pytest.approx(
            [abs(shear(x)) for x in distances], abs=0.005 * largest
        )
        forces = member["envelope"]["section_forces"]
        assert forces["max_Vf2_N"] == pytest.approx(largest, rel=0.005)

    def test_triangular_load(self, tmp_path):
        """Nothing at A rising to w at B: w L / 6 and w L / 3 on the supports,
        w L² / (9 √3) at L / √3, and 0.006522 w L⁴ / E I at 0.5193 L."""
        w, span = self.PEAK, self.SPAN
        data, lifts, forces = self._beam(tmp_path, values=[(0.0, 0.0), (0.0, -w)])
        assert lifts == pytest.approx([w * span / 6, w * span / 3], rel=1e-4)
        assert forces["max_Mf2_Nm"] == pytest.approx(
            w * span**2 / (9 * math.sqrt(3)), rel=FORCE_TOLERANCE
        )
        stiffness = PLANE_E * self.SIDE**4 / 12
        shear = PLANE_E / 2.6 * self.SIDE**2 * 5 / 6
        x = 0.5193 * span
        moment_there = w * span * x / 6 * (1 - (x / span) ** 2)
        expected = 0.006522 * w * span**4 / stiffness + moment_there / shear
        assert _max_vertical_deflection(data) == pytest.approx(expected, rel=0.01)
        self._assert_shear(
            data, lambda x: w * span / 6 - w * x**2 / (2 * span), w * span / 3
        )

    def test_load_on_part_of_the_beam(self, tmp_path):
        """w from 1.9 to 3.9 m, which starts and ends inside an element.

        2 w acting at 2.9 m: 0.55 w and 1.45 w on the supports. The shear
        is zero 1.55 m from B, where the moment is 1.19625 w.
        """
        w = self.PEAK
        data, lifts, forces = self._beam(
            tmp_path, values=[(0.0, -w), (0.0, -w)], locations=[1.9, 3.9]
        )
        assert lifts == pytest.approx([0.55 * w, 1.45 * w], rel=1e-4)
        assert forces["max_Mf2_Nm"] == pytest.approx(1.19625 * w, rel=FORCE_TOLERANCE)
        self._assert_shear(
            data, lambda x: w * (0.55 - min(max(x - 1.9, 0.0), 2.0)), 1.45 * w
        )

    def _deflection(self, bending: float, moment_at_the_middle: float) -> float:
        """Midspan deflection: ``bending`` times w L⁴ / E I, plus shear."""
        stiffness = PLANE_E * self.SIDE**4 / 12
        shear = PLANE_E / 2.6 * self.SIDE**2 * 5 / 6
        return (
            bending * self.PEAK * self.SPAN**4 / stiffness
            + moment_at_the_middle / shear
        )

    def test_sine_half_wave(self, tmp_path):
        """w at the middle: w L / π on each support, w L² / π² at midspan
        and w L⁴ / π⁴ E I, the one load a beam answers in its own shape."""
        w, span = self.PEAK, self.SPAN
        data, lifts, forces = self._beam(
            tmp_path, values=[(0.0, -w)], distribution="SINUS"
        )
        assert lifts == pytest.approx([w * span / math.pi] * 2, rel=1e-6)
        moment = w * span**2 / math.pi**2
        assert forces["max_Mf2_Nm"] == pytest.approx(moment, rel=FORCE_TOLERANCE)
        assert _max_vertical_deflection(data) == pytest.approx(
            self._deflection(1 / math.pi**4, moment), rel=0.01
        )
        self._assert_shear(
            data,
            lambda x: w * span / math.pi * math.cos(math.pi * x / span),
            w * span / math.pi,
        )

    def test_parabolic_half_wave(self, tmp_path):
        """w at the middle: w L / 3 on each support, 5 w L² / 48 at midspan
        and 61 w L⁴ / 5760 E I."""
        w, span = self.PEAK, self.SPAN
        data, lifts, forces = self._beam(
            tmp_path, values=[(0.0, -w)], distribution="PARABOLA"
        )
        assert lifts == pytest.approx([w * span / 3] * 2, rel=1e-6)
        moment = 5 * w * span**2 / 48
        assert forces["max_Mf2_Nm"] == pytest.approx(moment, rel=FORCE_TOLERANCE)
        assert _max_vertical_deflection(data) == pytest.approx(
            self._deflection(61 / 5760, moment), rel=0.01
        )
        self._assert_shear(
            data,
            lambda x: w * span / 3 - 2 * w * x**2 / span + 4 * w * x**3 / (3 * span**2),
            w * span / 3,
        )

    def test_series_of_point_forces(self, tmp_path):
        """P at 1.3 m and 2 P at 2.9 m, neither where a node would be.

        1.225 P and 1.775 P on the supports; the shear is 1.225 P, 0.225 P
        and 1.775 P, and the moment 1.5925 P at the first force and
        1.9525 P at the second.
        """
        force = self.PEAK
        data, lifts, forces = self._beam(
            tmp_path,
            values=[(0.0, -force), (0.0, -2 * force)],
            locations=[1.3, 2.9],
            distribution="DISCRETE",
        )
        assert lifts == pytest.approx([1.225 * force, 1.775 * force], rel=1e-6)
        assert forces["max_Mf2_Nm"] == pytest.approx(
            1.9525 * force, rel=FORCE_TOLERANCE
        )
        assert forces["max_Vf2_N"] == pytest.approx(1.775 * force, rel=FORCE_TOLERANCE)
        (member,) = data["members"]
        diagram = member["section_force_diagrams"]["Load"]
        between = [
            abs(shear)
            for at, shear in zip(diagram["distance_m"], diagram["Vf2_N"])
            if 1.5 < at < 2.7
        ]
        assert between
        assert between == pytest.approx([0.225 * force] * len(between), rel=0.02)

    def test_point_forces_along_a_rafter(self, tmp_path):
        """P along a rafter rising 3 in 4, given in the rafter's own axes:
        0.8 P and 0.6 P for the supports to hold."""
        force = self.PEAK
        data, _ = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (4, 3)},
            members=[("A", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            loads={},
            hinged=False,
            mesh_size=0.25,
            line_loads={
                ("A", "B"): dict(
                    values=[(force, 0.0)],
                    locations=[1.7],
                    distribution="DISCRETE",
                    local=True,
                )
            },
        )
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["fx_N"] == pytest.approx(-0.8 * force, rel=1e-5)
        assert total["fz_N"] == pytest.approx(-0.6 * force, rel=1e-5)

    def test_point_action_in_the_axes_of_its_member(self, tmp_path):
        """P and a moment on a rafter rising 3 in 4, in the rafter's own axes
        (`aiz.85`): 0.8 P and 0.6 P for the supports to hold. It was applied
        along global X."""
        force = self.PEAK
        data, warnings = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "M": (2, 1.5), "B": (4, 3)},
            members=[("A", "M"), ("M", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            loads={"M": (force, 0.0)},
            local_loads={"M": ("A", "M")},
            hinged=False,
            mesh_size=0.25,
        )
        assert not [w for w in warnings if "local axes" in w]
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["fx_N"] == pytest.approx(-0.8 * force, rel=1e-5)
        assert total["fz_N"] == pytest.approx(-0.6 * force, rel=1e-5)

    def test_point_action_in_the_axes_of_its_connection(self, tmp_path):
        """P on a joint of a level beam, along the x axis of the joint's own
        system, which rises 3 in 4 (`aiz.85`). Along the z axis of a joint
        with no system of its own it is a load along global Z."""
        force = self.PEAK
        model = dict(
            nodes={"A": (0, 0), "M": (2, 0), "B": (4, 0)},
            members=[("A", "M"), ("M", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            local_loads={"M": None},
            hinged=False,
            mesh_size=0.25,
        )
        data, warnings = _plane_run(
            tmp_path / "turned",
            loads={"M": (force, 0.0)},
            support_axes={"M": ((-0.6, 0.0, 0.8), (0.8, 0.0, 0.6))},
            **model,
        )
        assert not [w for w in warnings if "local axes" in w]
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["fx_N"] == pytest.approx(-0.8 * force, rel=1e-5)
        assert total["fz_N"] == pytest.approx(-0.6 * force, rel=1e-5)

        data, warnings = _plane_run(
            tmp_path / "level", loads={"M": (0.0, force)}, **model
        )
        assert not [w for w in warnings if "local axes" in w]
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["fx_N"] == pytest.approx(0.0, abs=1e-5 * force)
        assert total["fz_N"] == pytest.approx(-force, rel=1e-5)

    def test_snow_on_a_rafter(self, tmp_path):
        """A load per projected length on a rafter rising 3 in 4.

        w per metre of plan, 4 m of plan: 4 w on the supports, where a load
        per true length would put 5 w.
        """
        w = self.PEAK
        data, _ = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (4, 3)},
            members=[("A", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            loads={},
            hinged=False,
            mesh_size=0.25,
            line_loads={("A", "B"): dict(values=[(0.0, -w)], projected=True)},
        )
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["fz_N"] == pytest.approx(4 * w, rel=1e-5)


class TestAppliedMoments:
    """Moments applied to a 4 m beam, 0.1 m square (``aiz.58``).

    They stopped the analysis. CalculiX takes a moment on a rotation of a
    beam node and makes the node a knot; measured on hand-written input at
    the end of a member, between two elements and at an element's middle
    node, on 2.21 and 2.23.
    """

    MOMENT, SPAN, SIDE = 1000.0, 4.0, 0.1
    ENDS = {"A": (0, 0), "B": (4, 0)}

    def _run(self, tmp_path, **model):
        model.setdefault("loads", {})
        data, warnings = _plane_run(tmp_path, hinged=False, mesh_size=0.25, **model)
        assert not [w for w in warnings if w.startswith("CalculiX")]
        if solver_reports_clamped_reactions():
            assert not [w for w in warnings if "solver reported" in w]
        forces = [m["envelope"]["section_forces"] for m in data["members"]]
        return data, forces

    def _stiffness(self) -> float:
        return PLANE_E * self.SIDE**4 / 12

    def test_at_the_end_of_a_cantilever(self, tmp_path):
        """The same moment all along, M L² / 2 E I at the tip."""
        data, (forces,) = self._run(
            tmp_path,
            nodes=self.ENDS,
            members=[("A", "B")],
            supports={"A": PLANE_FIXED},
            moments={"B": (0.0, self.MOMENT, 0.0)},
        )
        assert forces["max_Mf2_Nm"] == pytest.approx(self.MOMENT, rel=1e-3)
        assert forces["max_Vf2_N"] < 1e-3 * self.MOMENT
        (reaction,) = data["supports"][0]["by_load_case"].values()
        assert reaction["my_Nm"] == pytest.approx(-self.MOMENT, rel=1e-3)
        # A case of a moment alone: the whole reaction is that moment too
        total = data["global_reactions"]["total"]
        assert total["applied_moment_Nm"] == pytest.approx([0.0, self.MOMENT, 0.0])
        assert total["my_Nm"] == pytest.approx(-self.MOMENT, rel=1e-3)
        assert total["moment_imbalance_Nm"] < 1e-3 * self.MOMENT
        assert _max_vertical_deflection(data) == pytest.approx(
            self.MOMENT * self.SPAN**2 / (2 * self._stiffness()), rel=0.01
        )

    def test_torque_at_the_end_of_a_cantilever(self, tmp_path):
        data, (forces,) = self._run(
            tmp_path,
            nodes=self.ENDS,
            members=[("A", "B")],
            supports={"A": PLANE_FIXED},
            moments={"B": (self.MOMENT, 0.0, 0.0)},
        )
        assert forces["max_T_Nm"] == pytest.approx(self.MOMENT, rel=1e-3)
        assert forces["max_Mf2_Nm"] < 1e-3 * self.MOMENT
        (reaction,) = data["supports"][0]["by_load_case"].values()
        assert reaction["mx_Nm"] == pytest.approx(-self.MOMENT, rel=1e-3)

    def test_where_two_members_meet(self, tmp_path):
        """In the middle of a simply supported beam: M / L on the supports,
        M / 2 either side of it, and M L² / (72 √3 E I) of deflection.

        The solver's stress at the joint is the mean of the two sides,
        which is nothing: the diagrams have what each member's own
        cross-sections lead to.
        """
        data, forces = self._run(
            tmp_path,
            nodes={"A": (0, 0), "M": (2, 0), "B": (4, 0)},
            members=[("A", "M"), ("M", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            moments={"M": (0.0, self.MOMENT, 0.0)},
        )
        lifts = [
            _support_at(data, (x, 0.0, 0.0))["by_load_case"]["Load"]["fz_N"]
            for x in (0.0, self.SPAN)
        ]
        assert lifts == pytest.approx(
            [-self.MOMENT / self.SPAN, self.MOMENT / self.SPAN], rel=1e-4
        )
        for member in forces:
            assert member["max_Mf2_Nm"] == pytest.approx(self.MOMENT / 2, rel=1e-3)
        before, after = [
            m["section_force_diagrams"]["Load"]["Mf2_Nm"] for m in data["members"]
        ]
        assert before[-1] == pytest.approx(-after[0], rel=1e-3)
        assert abs(before[-1]) == pytest.approx(self.MOMENT / 2, rel=1e-3)
        assert _max_vertical_deflection(data) == pytest.approx(
            self.MOMENT * self.SPAN**2 / (72 * math.sqrt(3) * self._stiffness()),
            rel=0.01,
        )

    def test_inside_a_member(self, tmp_path):
        """1.5 m along one member: M a / L before it and M b / L after."""
        data, (forces,) = self._run(
            tmp_path,
            nodes={"A": (0, 0), "M": (1.5, 0), "B": (4, 0)},
            members=[("A", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            moments={"M": (0.0, self.MOMENT, 0.0)},
        )
        assert forces["max_Mf2_Nm"] == pytest.approx(self.MOMENT * 2.5 / 4, rel=1e-3)
        diagram = data["members"][0]["section_force_diagrams"]["Load"]
        there = [
            moment
            for distance, moment in zip(diagram["distance_m"], diagram["Mf2_Nm"])
            if abs(distance - 1.5) < 1e-6
        ]
        assert sorted(abs(moment) for moment in there) == pytest.approx(
            [self.MOMENT * 1.5 / 4, self.MOMENT * 2.5 / 4], rel=1e-3
        )
        assert there[0] * there[1] < 0

    def test_with_loads_beside_it(self, tmp_path):
        """1 kN/m on the first half, 4 kN and the moment at midspan.

        3250 and 2750 N on the supports; 4500 N·m just before midspan and
        5500 just after, where the mean of the two is 5000.
        """
        data, forces = self._run(
            tmp_path,
            nodes={"A": (0, 0), "M": (2, 0), "B": (4, 0)},
            members=[("A", "M"), ("M", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            loads={"M": (0.0, -4000.0)},
            moments={"M": (0.0, self.MOMENT, 0.0)},
            line_loads={("A", "M"): dict(values=[(0.0, -1000.0)])},
        )
        lifts = [
            _support_at(data, (x, 0.0, 0.0))["by_load_case"]["Load"]["fz_N"]
            for x in (0.0, self.SPAN)
        ]
        assert lifts == pytest.approx([3250.0, 2750.0], rel=1e-4)
        assert forces[0]["max_Mf2_Nm"] == pytest.approx(4500.0, rel=FORCE_TOLERANCE)
        assert forces[1]["max_Mf2_Nm"] == pytest.approx(5500.0, rel=FORCE_TOLERANCE)

    def test_torque_along_a_cantilever(self, tmp_path):
        """500 N·m per metre: 2000 N·m at the root, and on the support."""
        data, (forces,) = self._run(
            tmp_path,
            nodes=self.ENDS,
            members=[("A", "B")],
            supports={"A": PLANE_FIXED},
            line_loads={("A", "B"): dict(values=[(0, 0)], moment=(500.0, 0, 0))},
        )
        assert forces["max_T_Nm"] == pytest.approx(2000.0, rel=1e-3)
        (reaction,) = data["supports"][0]["by_load_case"].values()
        assert reaction["mx_Nm"] == pytest.approx(-2000.0, rel=1e-3)

    def test_couple_along_a_beam(self, tmp_path):
        """500 N·m per metre about Y on a simply supported beam.

        The supports take 500 N each way and the shear is 500 N all along.
        The beam has no moment; the nodal moments leave a saw tooth of
        half of what one element carries.
        """
        data, (forces,) = self._run(
            tmp_path,
            nodes=self.ENDS,
            members=[("A", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            line_loads={("A", "B"): dict(values=[(0, 0)], moment=(0, 500.0, 0))},
        )
        lifts = [
            _support_at(data, (x, 0.0, 0.0))["by_load_case"]["Load"]["fz_N"]
            for x in (0.0, self.SPAN)
        ]
        assert lifts == pytest.approx([-500.0, 500.0], rel=1e-4)
        assert forces["max_Vf2_N"] == pytest.approx(500.0, rel=FORCE_TOLERANCE)
        assert forces["max_Mf2_Nm"] <= 500.0 * 0.25 / 2 * 1.01

    def test_at_a_clamped_support(self, tmp_path):
        """It goes into the support, with what the member brings.

        1 kN down at the tip and 500 N·m about Y, 300 about X at the root:
        the support resists 4500 and 300 N·m.
        """
        data, (forces,) = self._run(
            tmp_path,
            nodes=self.ENDS,
            members=[("A", "B")],
            supports={"A": PLANE_FIXED},
            loads={"B": (0.0, -1000.0)},
            moments={"A": (300.0, 500.0, 0.0)},
        )
        assert forces["max_Mf2_Nm"] == pytest.approx(4000.0, rel=FORCE_TOLERANCE)
        assert forces["max_T_Nm"] < 1.0
        (reaction,) = data["supports"][0]["by_load_case"].values()
        assert reaction["my_Nm"] == pytest.approx(-4500.0, rel=FORCE_TOLERANCE)
        assert reaction["mx_Nm"] == pytest.approx(-300.0, rel=1e-6)


class TestSolverReactionsAreChecked:
    """CalculiX 2.21 misreports the force at a support that holds a rotation.

    The same input gives the same displacements as 2.23 and other reactions,
    wrong by anything up to the size of the load. The results do not pass
    that on: such a support is checked against the ends of its members.
    """

    def _portal(self, tmp_path):
        output_dir = str(tmp_path / "out")
        result = analyze_ifc(
            ifc_path=os.path.join(IFC_DIR, "portal_01.ifc"),
            output_dir=output_dir,
            mesh_size=0.25,
        )
        assert result["status"] == "success", result.get("errors")
        with open(os.path.join(output_dir, "results.json")) as fh:
            return result, json.load(fh)

    def test_reactions_are_right_whatever_the_solver_says(self, tmp_path):
        """Each foot carries what the results in the file say, to 1 %."""
        _, data = self._portal(tmp_path)
        (total,) = data["global_reactions"]["by_load_case"].values()
        load = -total["applied_load_N"][2]
        assert load == pytest.approx(9600.0 * POUND_FORCE, rel=1e-6)
        expected = _portal_reactions_in_the_file()
        for support in data["supports"]:
            (reaction,) = support["by_load_case"].values()
            _, _, lift = expected[round(support["position_m"][0], 3)]
            assert reaction["fz_N"] == pytest.approx(lift, rel=FORCE_TOLERANCE)

    def test_the_results_say_where_the_forces_come_from(self, tmp_path):
        result, data = self._portal(tmp_path)
        (total,) = data["global_reactions"]["by_load_case"].values()
        sources = {support["forces"] for support in data["supports"]}
        warned = [w for w in result["warnings"] if "solver reported" in w["message"]]
        if solver_reports_clamped_reactions():
            assert sources == {"solver"}
            assert total["imbalance_N"] < 1e-6 * total["resultant_N"]
            assert not warned
        else:
            assert sources == {"member_end_forces"}
            (warning,) = warned
            assert "At 2 support(s) that hold a rotation" in warning["message"]
            assert "CalculiX 2.21 and earlier" in warning["message"]
            # The total is then that of the supports (`94g.7`): the
            # solver's own is 11 % short here
            assert total["forces"] == "supports"
            assert "the total given is that of the supports" in warning["message"]
            assert total["imbalance_N"] < 1e-3 * total["resultant_N"]

    def test_supports_the_solver_has_right_stay_its_own(self, tmp_path):
        """structure_01: two column feet and a wall foot, all clamped (`94g.7`).

        CalculiX 2.21 is wrong at the column feet only. The wall foot has no
        member end to check it against and was once marked unreliable
        because the whole did not balance; with the columns' forces replaced
        it does.
        """
        data = _run(
            os.path.join(IFC_DIR, "structure_01.ifc"), tmp_path, 0.5, gravity=True
        )
        total = data["global_reactions"]["total"]
        assert total["imbalance_N"] < 1e-3 * total["resultant_N"]
        assert total["moment_imbalance_Nm"] < 1e-3 * max(
            abs(v) for v in total["applied_moment_Nm"]
        )
        sources = sorted(s["forces"] for s in data["supports"])
        if solver_reports_clamped_reactions():
            assert sources == ["solver"] * 3
            assert total["forces"] == "solver"
        else:
            assert sources == ["member_end_forces"] * 2 + ["solver"]
            assert total["forces"] == "supports"
        (wall,) = [s for s in data["supports"] if s["type"] == "line"]
        assert wall["forces"] == "solver"
        assert wall["moments"] == "solver"


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
        # The load on the restrained edge nodes goes straight to ground; the
        # solver leaves it out of its total (7 % here) and the results add it
        assert data["global_reactions"]["total"]["fz_N"] == pytest.approx(
            pressure * self.A * self.B, rel=1e-4
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
        model = ifcopenshell.open(self.STRUCTURE)
        names = {
            entity.GlobalId: entity.Name
            for entity in model.by_type("IfcStructuralMember")
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


def _placed_variant(
    tmp_path, name: str, x_axis=(1.0, 0.0, 0.0), z_axis=(0.0, 0.0, 1.0)
) -> str:
    """An example with every item under a placement that moves and turns it.

    The placement is nested: its parent is 12, -7, 3 m away and a quarter
    turn about Z, and it adds 1.5, 2.5, -0.5 m in the parent's axes, turned
    again so that its x is along ``x_axis`` and its z along ``z_axis``.
    Offsets are written in the file's own length unit.
    """
    import ifcopenshell
    import ifcopenshell.util.unit

    model = ifcopenshell.open(os.path.join(IFC_DIR, f"{name}.ifc"))
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)

    def axes(offset, x_axis, z_axis=(0.0, 0.0, 1.0)):
        return model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity(
                "IfcCartesianPoint", [c / scale for c in offset]
            ),
            Axis=model.create_entity("IfcDirection", z_axis),
            RefDirection=model.create_entity("IfcDirection", x_axis),
        )

    parent = model.create_entity(
        "IfcLocalPlacement", RelativePlacement=axes((12.0, -7.0, 3.0), (0.0, 1.0, 0.0))
    )
    placement = model.create_entity(
        "IfcLocalPlacement",
        PlacementRelTo=parent,
        RelativePlacement=axes((1.5, 2.5, -0.5), x_axis, z_axis),
    )
    for kind in ("IfcStructuralItem", "IfcStructuralActivity"):
        for entity in model.by_type(kind):
            entity.ObjectPlacement = placement
    path = str(tmp_path / f"{name}_placed.ifc")
    model.write(path)
    return path


class TestSurfaceFields:
    """Forces and moments of surface members on their mesh (``94g.13.5``).

    ``slab_01`` as shipped is clamped along its two edges 5 m apart and
    free along the others: under its weight its middle is close to a strip
    with fixed ends, q L^2 / 12 at the clamps, q L^2 / 24 at midspan and
    q L / 2 of shear. The moments do not depend on the plate's stiffness.
    """

    SPAN, WIDTH = 5.0, 3.0

    def _slab(self, tmp_path):
        data = _run(SLAB, tmp_path, mesh_size=0.25, gravity=True)
        (member,) = [m for m in data["members"] if m["type"] == "surface"]
        points = np.array(member["surface_mesh"]["points_m"])
        fields = {
            k: np.array(v) for k, v in member["surface_fields"]["Gravity"].items()
        }
        weight = data["global_reactions"]["by_load_case"]["Gravity"]["fz_N"]
        return data, member, points, fields, weight / (self.SPAN * self.WIDTH)

    def _along_edge(self, points, values, x):
        on = np.where(np.abs(points[:, 0] - x) < 1e-6)[0]
        on = on[np.argsort(points[on, 1])]
        y = points[on, 1]
        return float(np.sum((values[on][1:] + values[on][:-1]) / 2 * np.diff(y)))

    def test_mesh_and_axes(self, tmp_path):
        _, member, points, fields, _ = self._slab(tmp_path)
        assert member["surface_axes"] == {
            "x": [1.0, 0.0, 0.0],
            "y": [0.0, 1.0, 0.0],
            "z": [0.0, 0.0, 1.0],
        }
        triangles = np.array(member["surface_mesh"]["triangles"])
        assert triangles.min() == 0 and triangles.max() == len(points) - 1
        # The triangles cover the slab once
        a, b, c = (points[triangles[:, i]] for i in range(3))
        area = np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2
        assert area == pytest.approx(self.SPAN * self.WIDTH, rel=1e-9)
        for values in fields.values():
            assert len(values) == len(points)

    def test_moments_and_shear_of_a_clamped_strip(self, tmp_path):
        """Within 2 % at the clamps (1.1 % measured) and 4 % at midspan
        (2.1 to 3.2 %), where the free edges of a plate take some of it."""
        _, _, points, fields, q = self._slab(tmp_path)
        L = self.SPAN
        middle = np.abs(points[:, 1] - self.WIDTH / 2) < 0.4
        for x in (0.0, L):
            at_clamp = middle & (np.abs(points[:, 0] - x) < 1e-6)
            # z is up: hogging puts the side it points to in tension
            assert fields["mx_Nm_per_m"][at_clamp] == pytest.approx(
                q * L**2 / 12, rel=0.02
            )
        midspan = middle & (np.abs(points[:, 0] - L / 2) < 0.15)
        assert fields["mx_Nm_per_m"][midspan] == pytest.approx(-q * L**2 / 24, rel=0.04)
        # Inside the span the shear is that of statics to 4 % of q L / 2
        inside = middle & (points[:, 0] > 0.3) & (points[:, 0] < L - 0.3)
        statics = -q * (L / 2 - points[inside, 0])
        assert np.abs(fields["vx_N_per_m"][inside] - statics).max() < 0.04 * q * L / 2
        assert np.abs(fields["nx_N_per_m"]).max() < 1e-3 * q * L
        assert np.abs(fields["ny_N_per_m"]).max() < 1e-3 * q * L

    def test_edges_carry_the_weight(self, tmp_path):
        """Shear and moment added up along each clamped edge, against statics."""
        _, _, points, fields, q = self._slab(tmp_path)
        L, B = self.SPAN, self.WIDTH
        for x, sign in ((0.0, -1.0), (L, 1.0)):
            shear = self._along_edge(points, fields["vx_N_per_m"], x)
            moment = self._along_edge(points, fields["mx_Nm_per_m"], x)
            assert shear == pytest.approx(sign * q * L * B / 2, rel=0.03)
            assert moment == pytest.approx(q * L**2 / 12 * B, rel=0.01)

    def test_wall_foot_carries_its_reaction(self, tmp_path):
        """structure_01's wall on a line support: its membrane forces along
        the foot add up to the support's reaction."""
        data = _run(
            os.path.join(IFC_DIR, "structure_01.ifc"), tmp_path, 0.25, gravity=True
        )
        (support,) = [s for s in data["supports"] if s["type"] == "line"]
        reaction = support["by_load_case"]["Gravity"]
        (wall,) = [
            m
            for m in data["members"]
            if m["type"] == "surface" and m["surface_axes"]["y"] == [0.0, 0.0, 1.0]
        ]
        points = np.array(wall["surface_mesh"]["points_m"])
        fields = {k: np.array(v) for k, v in wall["surface_fields"]["Gravity"].items()}
        foot = np.where(np.abs(points[:, 2]) < 1e-6)[0]
        foot = foot[np.argsort(points[foot, 1])]
        along = points[foot, 1]

        def integral(key):
            values = fields[key][foot]
            return float(np.sum((values[1:] + values[:-1]) / 2 * np.diff(along)))

        assert integral("ny_N_per_m") == pytest.approx(-reaction["fz_N"], rel=0.01)
        assert integral("nxy_N_per_m") == pytest.approx(-reaction["fy_N"], rel=0.02)


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
        # The mesh of a surface is not the same after the move, which moves
        # a small component by as much as a large one
        tolerance = 0.002 * before["max_displacement_m"]
        for moved, original in (("tx", "ty"), ("ty", "tx"), ("tz", "tz")):
            assert after[f"max_{moved}_m"] == pytest.approx(
                before[f"max_{original}_m"], rel=0, abs=tolerance
            )

        reactions = placed["global_reactions"]["by_load_case"]
        assert set(reactions) == set(shipped["global_reactions"]["by_load_case"])
        assert len(placed["members"]) == len(shipped["members"])
        _needs_solver_reactions()
        for case, reaction in shipped["global_reactions"]["by_load_case"].items():
            assert reactions[case]["fz_N"] == pytest.approx(reaction["fz_N"], rel=1e-4)
            assert abs(reactions[case]["fx_N"]) < 1e-3
            assert abs(reactions[case]["fy_N"]) < 1e-3

    @pytest.mark.parametrize("name", ["slab_01", "structure_01"])
    def test_turned_off_the_global_axes(self, tmp_path, name):
        """Turned by 30 degrees about Z, its supports and hinges are skew.

        ``slab_01`` is clamped about two edges, and ``structure_01`` has a
        line support that holds rotation about its edge, a point support
        that holds one rotation, and a slab hinged on a wall (``aiz.35``).
        Their axes are then no global ones, and the results are the same.
        """
        mesh = 0.5 if name == "structure_01" else 0.25
        angle = math.radians(30.0)
        runs = {
            "shipped": os.path.join(IFC_DIR, f"{name}.ifc"),
            "turned": _placed_variant(
                tmp_path, name, (math.cos(angle), math.sin(angle), 0.0)
            ),
        }
        shipped, turned = (
            _run(path, tmp_path / label, mesh_size=mesh, gravity=True)
            for label, path in runs.items()
        )

        before = shipped["global_displacements"]["envelope"]
        after = turned["global_displacements"]["envelope"]
        # The mesh of a surface is not the same after the move
        for key in ("max_displacement_m", "max_tz_m"):
            assert after[key] == pytest.approx(before[key], rel=0.002)

        weight = shipped["global_reactions"]["by_load_case"]["Gravity"]["fz_N"]
        assert len(turned["supports"]) == len(shipped["supports"])
        for original, moved in zip(shipped["supports"], turned["supports"]):
            # Along the support's own axes, which turn with the model
            expected = original.get("by_load_case_in_axes", original["by_load_case"])
            found = moved["by_load_case_in_axes"]["Gravity"]
            assert moved["restrained_in_axes"] == original.get(
                "restrained_in_axes", original["restrained"]
            )
            for key in ("fx_N", "fy_N", "fz_N"):
                assert found[key] == pytest.approx(
                    expected["Gravity"][key], abs=0.002 * weight
                )


COMBINED_DEAD, COMBINED_LIVE = 1.35, 1.5
LIVE_LINE_LOAD = (0.0, 3000.0, -5000.0)  # N/m, global


def _beam_with_two_cases(tmp_path, as_one_case: bool = False) -> str:
    """beam_01 with a second load case and three combinations of the two.

    Dead keeps its 20 kN at midspan; Live gets a line load with a sideways
    and a downward part. The combinations are ``1.5 Dead`` (as shipped),
    ``1.35 Dead + 1.5 Live`` and ``Dead - Live``.

    With ``as_one_case`` there are no combinations, and Dead holds both
    loads multiplied by the factors of the second one.
    """
    model = _beam_01()
    member = model.by_type("IfcStructuralCurveMember")[0]
    point_action = model.by_type("IfcStructuralPointAction")[0]
    scale = COMBINED_LIVE if as_one_case else 1.0
    action = model.create_entity(
        "IfcStructuralLinearAction",
        ifcopenshell.guid.new(),
        point_action.OwnerHistory,
        "benchmark live load",
        None,
        None,
        member.ObjectPlacement,
        member.Representation,
        model.create_entity(
            "IfcStructuralLoadLinearForce",
            None,
            *[scale * component / 1000.0 for component in LIVE_LINE_LOAD],
        ),
        "GLOBAL_COORDS",
        None,
        "TRUE_LENGTH",
    )
    model.create_entity(
        "IfcRelConnectsStructuralActivity",
        ifcopenshell.guid.new(),
        point_action.OwnerHistory,
        None,
        None,
        member,
        action,
    )
    cases = {case.Name: case for case in model.by_type("IfcStructuralLoadCase")}
    combinations = {
        group.Name: group
        for group in model.by_type("IfcStructuralLoadGroup")
        if group.PredefinedType == "LOAD_COMBINATION"
    }

    def assign(objects, group, factor=None):
        arguments = [
            ifcopenshell.guid.new(),
            point_action.OwnerHistory,
            None,
            None,
            objects,
            None,
            group,
        ]
        if factor is None:
            model.create_entity("IfcRelAssignsToGroup", *arguments)
        else:
            model.create_entity("IfcRelAssignsToGroupByFactor", *arguments, factor)

    if as_one_case:
        point_action.AppliedLoad.ForceZ *= COMBINED_DEAD
        assign([action], cases["Dead"])
        for relation in model.by_type("IfcRelAssignsToGroupByFactor"):
            model.remove(relation)
        for combination in combinations.values():
            model.remove(combination)
    else:
        assign([action], cases["Live"])
        for relation in model.by_type("IfcRelAssignsToGroupByFactor"):
            if relation.RelatingGroup == combinations["DCon2"]:
                model.remove(relation)
        assign([cases["Dead"]], combinations["DCon2"], COMBINED_DEAD)
        assign([cases["Live"]], combinations["DCon2"], COMBINED_LIVE)
        third = model.create_entity(
            "IfcStructuralLoadGroup",
            ifcopenshell.guid.new(),
            point_action.OwnerHistory,
            "Dead - Live",
            None,
            None,
            "LOAD_COMBINATION",
            "NOTDEFINED",
            "NOTDEFINED",
            None,
            None,
        )
        # No factor is a factor of one
        assign([cases["Dead"]], third)
        assign([cases["Live"]], third, -1.0)
    path = str(tmp_path / ("one_case.ifc" if as_one_case else "two_cases.ifc"))
    model.write(path)
    return path


def _only_curve_member(data: dict) -> dict:
    (member,) = [m for m in data["members"] if m["type"] == "curve"]
    return member


class TestLoadCombinations:
    """A combination is the sum of its load cases, each times its factor.

    The solver runs the load cases only. For what is linear in the load the
    figures are checked by hand; for what is not (a deflection with parts in
    two directions, von Mises stress, the largest stress in a section) they
    are checked against one load case holding the factored loads.
    """

    B = TestFixedFixedBeamPointLoad
    MESH = 0.25
    NAME = "DCon2"

    def _two_cases(self, tmp_path):
        return _run(_beam_with_two_cases(tmp_path), tmp_path, mesh_size=self.MESH)

    def test_combinations_are_listed_with_their_factors(self, tmp_path):
        data = self._two_cases(tmp_path)
        assert data["load_cases"] == ["Dead", "Live"]
        listed = {c["name"]: c["factors"] for c in data["load_combinations"]}
        assert listed == {
            "DCon1": {"Dead": 1.5},
            "DCon2": {"Dead": COMBINED_DEAD, "Live": COMBINED_LIVE},
            "Dead - Live": {"Dead": 1.0, "Live": -1.0},
        }

    def test_reactions_by_hand(self, tmp_path):
        _needs_solver_reactions()
        data = self._two_cases(tmp_path)
        length = self.B.LENGTH
        reactions = data["global_reactions"]["by_load_combination"]
        expected_fz = COMBINED_DEAD * self.B.LOAD - COMBINED_LIVE * (
            LIVE_LINE_LOAD[2] * length
        )
        expected_fy = -COMBINED_LIVE * LIVE_LINE_LOAD[1] * length
        assert reactions[self.NAME]["fz_N"] == pytest.approx(expected_fz, rel=1e-6)
        assert reactions[self.NAME]["fy_N"] == pytest.approx(expected_fy, rel=1e-6)
        assert reactions[self.NAME]["applied_load_N"] == pytest.approx(
            [0.0, -expected_fy, -expected_fz], rel=1e-6, abs=1e-6
        )
        assert reactions[self.NAME]["imbalance_N"] < 1e-6 * expected_fz
        # A negative factor takes a case away: 20 kN down less 5 kN/m down
        # over 4 m is nothing, and the sideways load is turned round
        assert reactions["Dead - Live"]["fz_N"] == pytest.approx(0.0, abs=0.01)
        assert reactions["Dead - Live"]["fy_N"] == pytest.approx(
            LIVE_LINE_LOAD[1] * length, rel=1e-6
        )
        assert reactions["DCon1"]["fz_N"] == pytest.approx(1.5 * self.B.LOAD, rel=1e-6)

    def test_section_forces_by_hand(self, tmp_path):
        """Fixed ends: P L / 8 and w L^2 / 12 at the supports, P/2 + w L / 2."""
        data = self._two_cases(tmp_path)
        length = self.B.LENGTH
        forces = _only_curve_member(data)["by_load_combination"][self.NAME][
            "section_forces"
        ]
        down = -COMBINED_LIVE * LIVE_LINE_LOAD[2]
        sideways = COMBINED_LIVE * LIVE_LINE_LOAD[1]
        point = COMBINED_DEAD * self.B.LOAD
        assert forces["max_Mf1_Nm"] == pytest.approx(
            point * length / 8 + down * length**2 / 12, rel=FORCE_TOLERANCE
        )
        assert forces["max_Vf1_N"] == pytest.approx(
            point / 2 + down * length / 2, rel=FORCE_TOLERANCE
        )
        assert forces["max_Mf2_Nm"] == pytest.approx(
            sideways * length**2 / 12, rel=FORCE_TOLERANCE
        )
        assert forces["max_Vf2_N"] == pytest.approx(
            sideways * length / 2, rel=FORCE_TOLERANCE
        )

    def test_support_moment_by_hand(self, tmp_path):
        data = self._two_cases(tmp_path)
        length = self.B.LENGTH
        moment = (
            COMBINED_DEAD * self.B.LOAD * length / 8
            - COMBINED_LIVE * LIVE_LINE_LOAD[2] * length**2 / 12
        )
        for support in data["supports"]:
            assert support["moments"] in MOMENT_SOURCES
            values = support["by_load_combination"][self.NAME]
            cases = support["by_load_case"]
            assert abs(values["my_Nm"]) == pytest.approx(moment, rel=FORCE_TOLERANCE)
            for key, value in values.items():
                if key == "resultant_N":
                    continue
                assert value == pytest.approx(
                    COMBINED_DEAD * cases["Dead"][key]
                    + COMBINED_LIVE * cases["Live"][key],
                    rel=1e-9,
                    abs=1e-6,
                )

    def test_same_as_one_case_holding_the_factored_loads(self, tmp_path):
        """Everything a member and a support has, to five figures.

        The result file gives six, and the sum is of rounded figures.
        """
        combined = self._two_cases(tmp_path)
        (tmp_path / "one").mkdir()
        single = _run(
            _beam_with_two_cases(tmp_path, as_one_case=True),
            tmp_path / "one",
            mesh_size=self.MESH,
        )
        assert "load_combinations" not in single

        def close(a, b, size):
            assert a == pytest.approx(b, rel=1e-5, abs=1e-5 * size)

        member = _only_curve_member(combined)
        reference = _only_curve_member(single)
        values = member["by_load_combination"][self.NAME]
        expected = reference["by_load_case"]["Dead"]
        for key in (
            "max_displacement_m",
            "max_relative_displacement_m",
            "max_von_mises_Pa",
            "max_normal_stress_Pa",
        ):
            close(values[key], expected[key], expected[key])
        for key, value in expected["section_forces"].items():
            close(values["section_forces"][key], value, 1.0e4)

        diagram = member["section_force_diagrams_by_combination"][self.NAME]
        reference_diagram = reference["section_force_diagrams"]["Dead"]
        assert diagram["distance_m"] == pytest.approx(reference_diagram["distance_m"])
        # A jump is made of six of the solver's figures, four times over
        for key, series in reference_diagram.items():
            close(diagram[key], series, 4.0e4)

        close(
            combined["global_displacements"]["by_load_combination"][self.NAME][
                "max_displacement_m"
            ],
            single["global_displacements"]["by_load_case"]["Dead"][
                "max_displacement_m"
            ],
            1.0e-3,
        )
        for support, other in zip(combined["supports"], single["supports"]):
            assert support["forces"] == other["forces"]
            for key, value in other["by_load_case"]["Dead"].items():
                close(support["by_load_combination"][self.NAME][key], value, 1.0e4)

    def test_largest_values_are_not_added(self, tmp_path):
        """Dead deflects down and Live also sideways: the sizes do not add.

        Nor do the largest moments: each case has its own at the supports,
        P L / 8 and w L^2 / 12, but one less the other has it at midspan,
        P L / 8 - w L^2 / 24.
        """
        data = self._two_cases(tmp_path)
        member = _only_curve_member(data)
        cases = member["by_load_case"]
        added = (
            COMBINED_DEAD * cases["Dead"]["max_displacement_m"]
            + COMBINED_LIVE * cases["Live"]["max_displacement_m"]
        )
        combined = member["by_load_combination"][self.NAME]["max_displacement_m"]
        assert combined < 0.99 * added
        difference = member["by_load_combination"]["Dead - Live"]
        assert difference["section_forces"]["max_Mf1_Nm"] == pytest.approx(
            self.B.LOAD * self.B.LENGTH / 8 + LIVE_LINE_LOAD[2] * self.B.LENGTH**2 / 24,
            rel=FORCE_TOLERANCE,
        )
        assert difference["section_forces"]["max_Mf1_Nm"] > 1.9 * abs(
            cases["Dead"]["section_forces"]["max_Mf1_Nm"]
            - cases["Live"]["section_forces"]["max_Mf1_Nm"]
        )

    def test_envelope_of_the_combinations(self, tmp_path):
        """Apart from the envelope of the load cases, which stays as it was."""
        data = self._two_cases(tmp_path)
        member = _only_curve_member(data)
        by_combination = member["by_load_combination"]
        assert member["combination_envelope"]["max_displacement_m"] == max(
            values["max_displacement_m"] for values in by_combination.values()
        )
        assert member["envelope"]["max_displacement_m"] == max(
            values["max_displacement_m"] for values in member["by_load_case"].values()
        )

    def test_buckling_has_no_combinations(self, tmp_path):
        output_dir = str(tmp_path / "buckling")
        result = analyze_ifc(
            ifc_path=_beam_with_two_cases(tmp_path),
            output_dir=output_dir,
            mesh_size=self.MESH,
            analysis_type="linear_buckling",
        )
        assert result["status"] == "success", result.get("errors")
        assert any(
            "3 load combination(s) of the file have no results" in w["message"]
            for w in result["warnings"]
        )
        with open(os.path.join(output_dir, "results.json")) as fh:
            assert "load_combinations" not in json.load(fh)


TRUSS_NODES = {"A": (0, 0), "B": (4, 0), "C": (8, 0), "D": (2, 3), "E": (6, 3)}
TRUSS_MEMBERS = [
    ("A", "B"),
    ("B", "C"),
    ("A", "D"),
    ("D", "B"),
    ("B", "E"),
    ("E", "C"),
    ("D", "E"),
]
TRUSS_LOAD = 10000.0
PLANE_E = 2.1e11
PLANE_WARNING = "The model is a plane structure"


def _beam_under_its_weight(tmp_path, coefficients) -> str:
    """beam_01 with no load but the share of its weight that Dead includes."""
    model = _beam_01(self_weight=True)
    for action in list(model.by_type("IfcStructuralAction")):
        for relation in model.get_inverse(action):
            if relation.is_a("IfcRelConnectsStructuralActivity"):
                model.remove(relation)
        model.remove(action)
    (dead,) = [c for c in model.by_type("IfcStructuralLoadCase") if c.Name == "Dead"]
    dead.SelfWeightCoefficients = coefficients
    path = str(tmp_path / "weight.ifc")
    model.write(path)
    return path


class TestSelfWeightOfALoadCase:
    """A load case includes the members' weight when the file says so (`aiz.71`).

    ``IfcStructuralLoadCase.SelfWeightCoefficients`` are the shares of it
    along global x, y and z. beam_01 is 4 m, fixed at both ends, 0.3 m
    square, 2500 kg/m3: w = 2207.25 N/m.
    """

    B = TestFixedFixedBeamPointLoad

    def test_weight_alone_by_hand(self, tmp_path):
        """w L in all, w L^2 / 12 at the ends, w L^4 / 384 EI and shear."""
        beam = self.B
        data = _run(_beam_under_its_weight(tmp_path, (0.0, 0.0, -1.0)), tmp_path)
        assert data["load_cases"] == ["Dead"]
        total = data["global_reactions"]["by_load_case"]["Dead"]
        assert total["fz_N"] == pytest.approx(beam.WEIGHT * beam.LENGTH, rel=1e-5)
        assert total["applied_load_N"][2] == pytest.approx(
            -beam.WEIGHT * beam.LENGTH, rel=1e-6
        )
        forces = _curve_member_envelope(data)["section_forces"]
        assert forces["max_Vf1_N"] == pytest.approx(
            beam.WEIGHT * beam.LENGTH / 2, rel=FORCE_TOLERANCE
        )
        assert forces["max_Mf1_Nm"] == pytest.approx(
            beam.WEIGHT * beam.LENGTH**2 / 12, rel=FORCE_TOLERANCE
        )
        shear_stiffness = beam.E / (2 * (1 + beam.NU)) * beam.AREA * 5 / 6
        expected = beam.WEIGHT * beam.LENGTH**4 / (
            384 * beam.E * beam.INERTIA
        ) + beam.WEIGHT * beam.LENGTH**2 / (8 * shear_stiffness)
        assert _max_vertical_deflection(data) == pytest.approx(
            expected, rel=DEFLECTION_TOLERANCE
        )

    def test_same_as_self_weight_asked_for(self, tmp_path):
        """``Dead`` and the ``Gravity`` case of ``gravity=True`` are one load."""
        path = _beam_under_its_weight(tmp_path, (0.0, 0.0, -1.0))
        output_dir = str(tmp_path / "out")
        result = analyze_ifc(
            ifc_path=path, output_dir=output_dir, mesh_size=MESH_SIZE, gravity=True
        )
        assert result["status"] == "success", result.get("errors")
        (warning,) = [
            w["message"] for w in result["warnings"] if "--gravity" in w["message"]
        ]
        assert "1 load case(s) of the file already include it: Dead" in warning
        with open(os.path.join(output_dir, "results.json")) as fh:
            data = json.load(fh)
        assert data["load_cases"] == ["Dead", "Gravity"]
        member = _only_curve_member(data)["by_load_case"]
        assert member["Dead"]["max_displacement_m"] == pytest.approx(
            member["Gravity"]["max_displacement_m"], rel=1e-9
        )
        reactions = data["global_reactions"]["by_load_case"]
        assert reactions["Dead"]["fz_N"] == pytest.approx(
            reactions["Gravity"]["fz_N"], rel=1e-9
        )

    def test_share_of_the_weight(self, tmp_path):
        beam = self.B
        whole = _run(_beam_under_its_weight(tmp_path, (0.0, 0.0, -1.0)), tmp_path, 0.5)
        part = _run(_beam_under_its_weight(tmp_path, (0.0, 0.0, -0.4)), tmp_path, 0.25)
        assert part["global_reactions"]["total"]["fz_N"] == pytest.approx(
            0.4 * beam.WEIGHT * beam.LENGTH, rel=1e-5
        )
        assert _max_vertical_deflection(part) == pytest.approx(
            0.4 * _max_vertical_deflection(whole), rel=DEFLECTION_TOLERANCE
        )

    def test_weight_acting_sideways(self, tmp_path):
        """Coefficients are along the global axes: (0, -1, 0) pulls along -Y."""
        beam = self.B
        data = _run(_beam_under_its_weight(tmp_path, (0.0, -1.0, 0.0)), tmp_path)
        weight = beam.WEIGHT * beam.LENGTH
        total = data["global_reactions"]["total"]
        assert total["applied_load_N"] == pytest.approx([0.0, -weight, 0.0], rel=1e-6)
        moved = data["global_displacements"]["envelope"]
        assert moved["max_ty_m"] > 100 * moved["max_tz_m"]
        # CalculiX 2.21 reports a vertical force at these clamped supports
        _needs_solver_reactions()
        assert total["fy_N"] == pytest.approx(weight, rel=1e-5)
        assert abs(total["fz_N"]) < 1e-6 * weight

    def test_combination_includes_it(self, tmp_path):
        """beam_01 as shipped: ``DCon1`` is 1.5 Dead, weight and all."""
        beam = self.B
        data = _run(BEAM, tmp_path)
        total = data["global_reactions"]["by_load_combination"]["DCon1"]
        assert total["fz_N"] == pytest.approx(
            1.5 * (beam.LOAD + beam.WEIGHT * beam.LENGTH), rel=1e-5
        )
        case = data["global_reactions"]["by_load_case"]["Dead"]
        assert total["applied_moment_Nm"] == pytest.approx(
            [1.5 * v for v in case["applied_moment_Nm"]]
        )
        assert max(abs(v) for v in total["applied_moment_Nm"]) > beam.LOAD
        forces = _only_curve_member(data)["by_load_combination"]["DCon1"]
        assert forces["section_forces"]["max_Mf1_Nm"] == pytest.approx(
            1.5 * (beam.LOAD * beam.LENGTH / 8 + beam.WEIGHT * beam.LENGTH**2 / 12),
            rel=FORCE_TOLERANCE,
        )

    def test_weightless_material_is_refused(self, tmp_path):
        """The weight of a member cannot be made up."""
        model = _beam_01(self_weight=True)
        for pset in model.by_type("IfcMaterialProperties"):
            pset.Properties = [p for p in pset.Properties if p.Name != "MassDensity"]
        path = str(tmp_path / "weightless.ifc")
        model.write(path)
        with pytest.raises(
            ModelExtractionError, match="Load case Dead includes self-weight"
        ):
            analyze_ifc(
                ifc_path=path, output_dir=str(tmp_path / "out"), mesh_size=MESH_SIZE
            )


def _plane_run(tmp_path, mesh_size=0.5, analysis_type="linear_static", **model):
    """Analyse a ``tests.helpers.plane_model``; returns results and warnings."""
    path = plane_model(str(tmp_path / "plane.ifc"), **model)
    output_dir = str(tmp_path / "out")
    result = analyze_ifc(
        ifc_path=path,
        output_dir=output_dir,
        mesh_size=mesh_size,
        analysis_type=analysis_type,
    )
    assert result["status"] == "success", result.get("errors")
    with open(os.path.join(output_dir, "results.json")) as fh:
        return json.load(fh), [w["message"] for w in result["warnings"]]


def _member_names(path: str) -> dict:
    """The name of each curve member of a file, by its GlobalId."""
    # The file must outlive its entities, or they are deleted with it
    model = ifcopenshell.open(path)
    return {
        member.GlobalId: member.Name
        for member in model.by_type("IfcStructuralCurveMember")
    }


def _axial_forces(data: dict, path: str) -> dict:
    """Axial force of each member by its name in the file, tension positive."""
    names = _member_names(path)
    forces = {}
    for member in data["members"]:
        envelope = member["envelope"]["section_forces"]
        tension, compression = (
            envelope["max_tension_N"],
            envelope["max_compression_N"],
        )
        forces[names[member["ifc_guid"]]] = (
            tension if tension > compression else -compression
        )
    return forces


class TestPlaneTruss:
    """A pin-jointed truss in the X-Z plane, 10 kN down at midspan.

    Two panels of 4 m, 3 m high: bottom chord A-B-C, top chord D-E, four
    diagonals. By the method of joints the reactions are P/2, the diagonals
    carry P sqrt(13)/6, the bottom chord P/3 and the top chord 2P/3. The
    deflection under the load is sum(F^2 L) / (P E A), by virtual work.

    Supported as its picture is, in X and Z only, nothing holds it across
    its plane and every bar can spin; it came out with 19 times its
    deflection (0.71 mm for 0.0375). It is now held in its plane, and says so.
    """

    SIDE = 0.05  # thin bars: displacements are read on their faces

    def _truss(self, tmp_path, supports, **kwargs):
        model = dict(
            nodes=TRUSS_NODES,
            members=TRUSS_MEMBERS,
            supports=supports,
            loads={"B": (0.0, -TRUSS_LOAD)},
            side=self.SIDE,
        )
        model.update(kwargs)
        return _plane_run(tmp_path, **model)

    def _expected_forces(self):
        diagonal = TRUSS_LOAD * 13**0.5 / 6
        return {
            "AB": TRUSS_LOAD / 3,
            "BC": TRUSS_LOAD / 3,
            "AD": -diagonal,
            "DB": diagonal,
            "BE": diagonal,
            "EC": -diagonal,
            "DE": -2 * TRUSS_LOAD / 3,
        }

    def _expected_deflection(self):
        lengths = {"AB": 4.0, "BC": 4.0, "DE": 4.0}
        work = sum(
            force**2 * lengths.get(name, 13**0.5)
            for name, force in self._expected_forces().items()
        )
        return work / (TRUSS_LOAD * PLANE_E * self.SIDE**2)

    @pytest.mark.parametrize(
        "supports",
        [
            {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D},
            {"A": PLANE_PIN, "C": PLANE_ROLLER},
        ],
        ids=["supported in its plane only", "supported across it too"],
    )
    def test_member_forces_and_deflection(self, tmp_path, supports):
        data, warnings = self._truss(tmp_path, supports)
        forces = _axial_forces(data, str(tmp_path / "plane.ifc"))
        for name, expected in self._expected_forces().items():
            assert forces[name] == pytest.approx(expected, rel=1e-3), name
        for member in data["members"]:
            bending = member["envelope"]["section_forces"]
            assert bending["max_Mf1_Nm"] < 1.0 and bending["max_Mf2_Nm"] < 1.0
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(
            self._expected_deflection(), rel=0.01
        )
        # Nothing leaves the plane
        assert envelope.get("max_ty_m", 0.0) < 0.01 * envelope["max_tz_m"]
        reaction = data["global_reactions"]["by_load_case"]["Load"]
        assert reaction["fz_N"] == pytest.approx(TRUSS_LOAD, rel=1e-6)
        for support in data["supports"]:
            assert support["by_load_case"]["Load"]["fz_N"] == pytest.approx(
                TRUSS_LOAD / 2, rel=1e-6
            )

    def test_it_says_what_it_held(self, tmp_path):
        _, warnings = self._truss(tmp_path, {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D})
        (warning,) = [w for w in warnings if PLANE_WARNING in w]
        assert "parallel to global X and Z" in warning
        assert "12 movement(s) out of the plane are unrestrained" in warning
        assert "every node is held along Y" in warning
        assert not [w for w in warnings if "free to spin" in w and w != warning]

    def test_rigid_joints_change_little(self, tmp_path):
        """Secondary bending: the bar forces of the pinned truss, within 1 %."""
        data, warnings = self._truss(
            tmp_path, {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D}, hinged=False
        )
        assert [w for w in warnings if PLANE_WARNING in w]
        forces = _axial_forces(data, str(tmp_path / "plane.ifc"))
        for name, expected in self._expected_forces().items():
            assert forces[name] == pytest.approx(expected, rel=0.01), name
        assert data["global_displacements"]["envelope"]["max_tz_m"] == pytest.approx(
            self._expected_deflection(), rel=0.01
        )

    def test_load_across_the_plane_is_left_alone(self, tmp_path):
        """Then it is a space structure, and holding it would hide the load."""
        _, warnings = self._truss(
            tmp_path, {"A": PLANE_PIN, "C": PLANE_ROLLER}, load_y=1.0
        )
        assert not [w for w in warnings if PLANE_WARNING in w]

    def test_buckling_is_left_alone(self, tmp_path):
        """Held in its plane it could not buckle out of it."""
        _, warnings = self._truss(
            tmp_path,
            {"A": PLANE_PIN, "C": PLANE_ROLLER},
            analysis_type="linear_buckling",
            hinged=False,
        )
        assert not [w for w in warnings if PLANE_WARNING in w]


class TestSolverWarnings:
    """CalculiX's own warnings are in the results (`aiz.66`).

    None of them used to be. The one the example models drew was about our
    own rigid links, which are meant to weigh nothing and now say so.
    """

    def test_rigid_links_draw_none(self, tmp_path):
        output_dir = str(tmp_path / "out")
        result = analyze_ifc(
            ifc_path=os.path.join(IFC_DIR, "grid_of_beams.ifc"),
            output_dir=output_dir,
            mesh_size=0.5,
            gravity=True,
        )
        assert result["status"] == "success", result.get("errors")
        with open(os.path.join(output_dir, "analysis.inp")) as fh:
            assert "MAT_RIGID_LINK" in fh.read()
        assert not [w for w in result["warnings"] if "CalculiX" in w["message"]]


class TestBucklingResults:
    """What a buckling analysis reports (`aiz.73`).

    The result file has the displacements under the loads and then one
    normalised shape per mode. The shapes were listed as load cases
    ``step_2`` and so on, and each drew a warning that the model moves by
    its own size; the factors were not in ``results.json`` at all.
    """

    HEIGHT, SIDE, LOAD = 3.0, 0.1, 10000.0

    def _column(self, tmp_path, analysis_type="linear_buckling"):
        """A pin-ended column under a load on its top."""
        return _plane_run(
            tmp_path,
            mesh_size=0.25,
            analysis_type=analysis_type,
            nodes={"A": (0, 0), "B": (0, self.HEIGHT)},
            members=[("A", "B")],
            supports={"A": PLANE_PIN, "B": (True, True, False, False, False, False)},
            loads={"B": (0.0, -self.LOAD)},
            side=self.SIDE,
            hinged=False,
        )

    def test_first_factor_is_the_euler_load(self, tmp_path):
        data, _ = self._column(tmp_path)
        euler = math.pi**2 * PLANE_E * self.SIDE**4 / 12 / self.HEIGHT**2
        modes = data["buckling"]["modes"]
        assert data["analysis_type"] == "linear_buckling"
        assert [mode["mode"] for mode in modes] == list(range(1, len(modes) + 1))
        assert modes[0]["factor"] == pytest.approx(euler / self.LOAD, rel=0.02)

    def test_mode_shapes_along_the_member(self, tmp_path):
        """A half sine sideways, and every mode the factors name (94g.13.4).

        The section is square, so the first mode may lean any way across.
        Each mode is scaled to a largest translation of one: the solver's
        own scale was 5.6e-4 for the first mode and 2.3e-5 for the tenth.
        """
        data, _ = self._column(tmp_path)
        (member,) = data["members"]
        shapes = member["mode_shapes"]
        modes = data["buckling"]["modes"]
        assert sorted(shapes) == sorted(f"Mode {m['mode']}" for m in modes)
        first = shapes["Mode 1"]
        across = [math.hypot(x, y) for x, y in zip(first["ux_m"], first["uy_m"])]
        largest = max(across)
        assert largest == pytest.approx(1.0)
        for shape in shapes.values():
            assert max(
                math.sqrt(x * x + y * y + z * z)
                for x, y, z in zip(shape["ux_m"], shape["uy_m"], shape["uz_m"])
            ) == pytest.approx(1.0)
        for distance, value in zip(first["distance_m"], across):
            assert value / largest == pytest.approx(
                math.sin(math.pi * distance / self.HEIGHT), abs=2e-3
            )
        assert max(abs(v) for v in first["uz_m"]) < 1e-2 * largest

    def test_mode_shapes_are_not_load_cases(self, tmp_path):
        data, warnings = self._column(tmp_path)
        (case,) = data["load_cases"]
        assert case == data["buckling"]["reference_load_case"]
        assert list(data["global_displacements"]["by_load_case"]) == [case]
        for member in data["members"]:
            assert list(member["by_load_case"]) == [case]
        assert not [w for w in warnings if "probably" in w]

    def test_the_results_are_those_of_the_loads(self, tmp_path):
        """The one set of results is what a static analysis gives."""
        data, _ = self._column(tmp_path)
        (tmp_path / "static").mkdir()
        static, _ = self._column(tmp_path / "static", "linear_static")
        (case,) = static["load_cases"]
        assert data["global_displacements"]["envelope"] == pytest.approx(
            static["global_displacements"]["by_load_case"][case]
        )
        shortening = self.LOAD * self.HEIGHT / (PLANE_E * self.SIDE**2)
        assert data["global_displacements"]["envelope"]["max_tz_m"] == pytest.approx(
            shortening, rel=0.05
        )

    def test_truss_draws_no_warning_about_its_size(self, tmp_path):
        _, warnings = _plane_run(
            tmp_path,
            analysis_type="linear_buckling",
            nodes=TRUSS_NODES,
            members=TRUSS_MEMBERS,
            supports={"A": PLANE_PIN, "C": PLANE_ROLLER},
            loads={"B": (0.0, -TRUSS_LOAD)},
            side=0.1,
            hinged=False,
        )
        assert not [w for w in warnings if "probably" in w]

    def test_static_analysis_says_what_it_is(self, tmp_path):
        data = _run(CANTILEVER, tmp_path, gravity=True)
        assert data["analysis_type"] == "linear_static"
        assert "buckling" not in data


class TestPlaneFrame:
    """A portal in the X-Z plane, 3 m high and 4 m wide, pushed sideways.

    Columns and beam of one section, 10 kN along X at the top of a column.
    With k = (I_beam / L) / (I_column / h) = 0.75:

    - feet pinned: P/2 shear in each column, P h / 2 at each corner;
    - feet fixed: (P h / 2)(3k + 1)/(6k + 1) at the feet and
      (P h / 2) 3k / (6k + 1) at the corners.
    """

    HEIGHT, WIDTH, LOAD, SIDE = 3.0, 4.0, 10000.0, 0.1
    NODES = {"A": (0, 0), "B": (0, 3), "C": (4, 3), "D": (4, 0)}
    MEMBERS = [("A", "B"), ("B", "C"), ("C", "D")]

    def _portal(self, tmp_path, supports):
        return _plane_run(
            tmp_path,
            nodes=self.NODES,
            members=self.MEMBERS,
            supports=supports,
            loads={"B": (self.LOAD, 0.0)},
            hinged=False,
            mesh_size=0.25,
        )

    def _moments(self, data, tmp_path):
        names = _member_names(str(tmp_path / "plane.ifc"))
        return {
            names[m["ifc_guid"]]: m["section_force_diagrams"]["Load"]["Mf2_Nm"]
            for m in data["members"]
        }

    def _stiffness(self):
        return PLANE_E * self.SIDE**4 / 12

    def test_pinned_feet(self, tmp_path):
        """Nothing stops it falling over about the line through its feet."""
        data, warnings = self._portal(tmp_path, {"A": PLANE_PIN, "D": PLANE_PIN})
        (warning,) = [w for w in warnings if PLANE_WARNING in w]
        assert "1 movement(s) out of the plane" in warning
        corner = self.LOAD * self.HEIGHT / 2
        moments = self._moments(data, tmp_path)
        assert abs(moments["AB"][0]) < 0.001 * corner
        assert abs(moments["AB"][-1]) == pytest.approx(corner, rel=FORCE_TOLERANCE)
        assert abs(moments["CD"][0]) == pytest.approx(corner, rel=FORCE_TOLERANCE)
        assert abs(moments["CD"][-1]) < 0.001 * corner
        # Sway: each column as a cantilever from the corner, plus the
        # rotation of the corners
        sway = (
            self.LOAD / 2 * self.HEIGHT**3 / (3 * self._stiffness())
            + corner * self.WIDTH / (6 * self._stiffness()) * self.HEIGHT
        )
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tx_m"] == pytest.approx(sway, rel=DEFLECTION_TOLERANCE)
        assert envelope.get("max_ty_m", 0.0) < 0.001 * envelope["max_tx_m"]
        for support in data["supports"]:
            assert abs(support["by_load_case"]["Load"]["fx_N"]) == pytest.approx(
                self.LOAD / 2, rel=1e-3
            )
            assert abs(support["by_load_case"]["Load"]["fz_N"]) == pytest.approx(
                self.LOAD * self.HEIGHT / self.WIDTH, rel=1e-3
            )

    def test_fixed_feet_by_hand(self, tmp_path):
        data, warnings = self._portal(
            tmp_path, {"A": PLANE_FIXED_2D, "D": PLANE_FIXED_2D}
        )
        assert [w for w in warnings if PLANE_WARNING in w]
        k = (1 / self.WIDTH) / (1 / self.HEIGHT)
        half = self.LOAD * self.HEIGHT / 2
        foot = half * (3 * k + 1) / (6 * k + 1)
        corner = half * 3 * k / (6 * k + 1)
        moments = self._moments(data, tmp_path)
        assert abs(moments["AB"][0]) == pytest.approx(foot, rel=FORCE_TOLERANCE)
        assert abs(moments["AB"][-1]) == pytest.approx(corner, rel=FORCE_TOLERANCE)
        assert abs(moments["CD"][0]) == pytest.approx(corner, rel=FORCE_TOLERANCE)
        assert abs(moments["CD"][-1]) == pytest.approx(foot, rel=FORCE_TOLERANCE)
        sway = (
            self.LOAD
            * self.HEIGHT**3
            / (12 * self._stiffness())
            * (3 * k + 2)
            / (6 * k + 1)
        )
        assert data["global_displacements"]["envelope"]["max_tx_m"] == pytest.approx(
            sway, rel=DEFLECTION_TOLERANCE
        )
        # The moment each foot is held with
        for support in data["supports"]:
            assert support["moments"] in MOMENT_SOURCES
            assert abs(support["by_load_case"]["Load"]["my_Nm"]) == pytest.approx(
                foot, rel=FORCE_TOLERANCE
            )

    def test_held_in_its_plane_it_is_the_fully_fixed_frame(self, tmp_path):
        """What is added restrains nothing the frame does in its plane.

        Feet fixed in all six directions need no help and get none; the same
        frame with feet fixed in the plane only gives the same answer.
        """
        (tmp_path / "space").mkdir()
        (tmp_path / "plane").mkdir()
        space, space_warnings = self._portal(
            tmp_path / "space", {"A": PLANE_FIXED, "D": PLANE_FIXED}
        )
        plane, plane_warnings = self._portal(
            tmp_path / "plane", {"A": PLANE_FIXED_2D, "D": PLANE_FIXED_2D}
        )
        assert not [w for w in space_warnings if PLANE_WARNING in w]
        assert [w for w in plane_warnings if PLANE_WARNING in w]
        assert plane["global_displacements"]["envelope"]["max_tx_m"] == pytest.approx(
            space["global_displacements"]["envelope"]["max_tx_m"], rel=1e-5
        )
        for held, free in zip(plane["members"], space["members"]):
            for key, value in free["envelope"]["section_forces"].items():
                assert held["envelope"]["section_forces"][key] == pytest.approx(
                    value, rel=1e-4, abs=1.0
                ), key


class TestSkewPlaneStructure:
    """The truss and the portal above turned 30 degrees about Z (94g.9).

    Their plane is then parallel to no two global axes, and they were left
    unheld: a mechanism. Every node is now held across the plane by an
    equation, and a member that can spin by an arm across it. The answer is
    that of the structure in the X-Z plane, turned.
    """

    TURN = 30.0

    def _turned(self, horizontal):
        angle = math.radians(self.TURN)
        return horizontal * math.cos(angle), horizontal * math.sin(angle)

    def test_truss(self, tmp_path):
        truss = TestPlaneTruss()
        (tmp_path / "flat").mkdir()
        flat, _ = truss._truss(
            tmp_path / "flat", {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D}
        )
        data, warnings = truss._truss(
            tmp_path, {"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D}, turn=self.TURN
        )
        (warning,) = [w for w in warnings if PLANE_WARNING in w]
        assert "the normal is (-0.5, 0.866, 0)" in warning
        assert "12 movement(s) out of the plane are unrestrained" in warning
        assert "every node is held across the plane" in warning
        forces = _axial_forces(data, str(tmp_path / "plane.ifc"))
        for name, expected in truss._expected_forces().items():
            assert forces[name] == pytest.approx(expected, rel=1e-3), name
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(
            truss._expected_deflection(), rel=0.01
        )
        # Its own movement in the plane, turned: nothing leaves it
        before = flat["global_displacements"]["envelope"]
        along_x, along_y = self._turned(before["max_tx_m"])
        assert envelope["max_tx_m"] == pytest.approx(along_x, rel=1e-3)
        assert envelope["max_ty_m"] == pytest.approx(along_y, rel=1e-3)
        assert envelope["max_tz_m"] == pytest.approx(before["max_tz_m"], rel=1e-3)
        for support in data["supports"]:
            assert support["by_load_case"]["Load"]["fz_N"] == pytest.approx(
                TRUSS_LOAD / 2, rel=1e-6
            )

    def test_portal_with_fixed_feet(self, tmp_path):
        """Its feet hold rotation about the normal: a skew support each."""
        portal = TestPlaneFrame()
        data, warnings = _plane_run(
            tmp_path,
            nodes=portal.NODES,
            members=portal.MEMBERS,
            supports={"A": PLANE_FIXED_2D, "D": PLANE_FIXED_2D},
            loads={"B": (portal.LOAD, 0.0)},
            hinged=False,
            mesh_size=0.25,
            turn=self.TURN,
        )
        (warning,) = [w for w in warnings if PLANE_WARNING in w]
        assert "3 movement(s)" in warning
        k = (1 / portal.WIDTH) / (1 / portal.HEIGHT)
        half = portal.LOAD * portal.HEIGHT / 2
        foot = half * (3 * k + 1) / (6 * k + 1)
        corner = half * 3 * k / (6 * k + 1)
        moments = portal._moments(data, tmp_path)
        assert abs(moments["AB"][0]) == pytest.approx(foot, rel=FORCE_TOLERANCE)
        assert abs(moments["AB"][-1]) == pytest.approx(corner, rel=FORCE_TOLERANCE)
        assert abs(moments["CD"][-1]) == pytest.approx(foot, rel=FORCE_TOLERANCE)
        for member in data["members"]:
            # No bending out of the plane
            assert member["envelope"]["section_forces"]["max_Mf1_Nm"] < 1e-4 * foot
        sway = (
            portal.LOAD
            * portal.HEIGHT**3
            / (12 * portal._stiffness())
            * (3 * k + 2)
            / (6 * k + 1)
        )
        along_x, along_y = self._turned(sway)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tx_m"] == pytest.approx(along_x, rel=DEFLECTION_TOLERANCE)
        assert envelope["max_ty_m"] == pytest.approx(along_y, rel=DEFLECTION_TOLERANCE)
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert math.hypot(total["fx_N"], total["fy_N"]) == pytest.approx(
            portal.LOAD, rel=1e-5
        )


def _shear_wall(tmp_path, turn: float) -> str:
    """slab_01 stood up as a wall 5 m high and 3 m wide, pushed sideways.

    Its edge at x = 0 is the foot, held in every translation along it and
    free to turn about it; the other edge is free. A uniform push of
    ``SHEAR_WALL_PUSH`` along the slab's y, in its plane, is horizontal.
    The placement of every item turns the wall about Z by ``turn`` degrees
    from the global X-Z plane.
    """
    model = ifcopenshell.open(SLAB)
    for relation in model.by_type("IfcRelConnectsStructuralMember"):
        relation.AppliedCondition = None
    foot, top = sorted(
        model.by_type("IfcStructuralCurveConnection"), key=lambda c: c.id()
    )
    foot.AppliedCondition = _edge_condition(
        model, (True, True, True, False, False, False)
    )
    for relation in list(model.get_inverse(top)):
        if relation.is_a("IfcRelConnectsStructuralMember"):
            model.remove(relation)
        elif relation.is_a("IfcRelAssignsToGroup"):
            relation.RelatedObjects = [o for o in relation.RelatedObjects if o != top]
    model.remove(top)
    for action in list(model.by_type("IfcStructuralAction")):
        for relation in model.get_inverse(action):
            if relation.is_a("IfcRelConnectsStructuralActivity"):
                model.remove(relation)
        model.remove(action)
    wall = model.by_type("IfcStructuralSurfaceMember")[0]
    _add_area_load(model, wall, (0.0, SHEAR_WALL_PUSH, 0.0))
    angle = math.radians(turn)
    placement = model.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint", (0.0, 0.0, 0.0)),
            Axis=model.create_entity(
                "IfcDirection", (-math.sin(angle), math.cos(angle), 0.0)
            ),
            RefDirection=model.create_entity("IfcDirection", (0.0, 0.0, 1.0)),
        ),
    )
    for kind in ("IfcStructuralItem", "IfcStructuralActivity"):
        for entity in model.by_type(kind):
            entity.ObjectPlacement = placement
    path = str(tmp_path / "wall.ifc")
    model.write(path)
    return path


SHEAR_WALL_PUSH = 1000.0  # N/m2


class TestShearWall:
    """A wall in its own plane on a line support at its foot (94g.9).

    Held along its foot in translation only, it can fall over about it, and
    surface members were never taken for a plane structure: it was a
    mechanism. Held across its plane, it is a deep cantilever: Timoshenko's,
    w H^4 / 8 EI + w H^2 / 2 (5/6) G A with w = q b, to a few percent (its
    foot is held across the whole width, which no beam is), and the moment
    at its foot is w H^2 / 2 by statics.
    """

    HEIGHT, WIDTH, THICKNESS, E, NU = 5.0, 3.0, 0.2, 2.1e8, 0.2

    def _run(self, tmp_path, turn):
        output_dir = str(tmp_path / "out")
        result = analyze_ifc(
            ifc_path=_shear_wall(tmp_path, turn),
            output_dir=output_dir,
            mesh_size=0.25,
        )
        assert result["status"] == "success", result.get("errors")
        with open(os.path.join(output_dir, "results.json")) as fh:
            return json.load(fh), [w["message"] for w in result["warnings"]]

    def _push(self):
        return SHEAR_WALL_PUSH * self.WIDTH

    def test_cantilever_by_hand(self, tmp_path):
        data, warnings = self._run(tmp_path, 0.0)
        (warning,) = [w for w in warnings if PLANE_WARNING in w]
        assert "parallel to global X and Z" in warning
        assert "1 movement(s)" in warning
        w = self._push()
        inertia = self.THICKNESS * self.WIDTH**3 / 12
        shear = self.E / (2 * (1 + self.NU)) * 5 / 6 * self.THICKNESS * self.WIDTH
        expected = w * self.HEIGHT**4 / (
            8 * self.E * inertia
        ) + w * self.HEIGHT**2 / (2 * shear)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tx_m"] == pytest.approx(expected, rel=0.03)
        # Across it only the faces move, as the wall thins and thickens
        assert envelope.get("max_ty_m", 0.0) < 0.01 * envelope["max_tx_m"]
        total = data["global_reactions"]["by_load_case"]["Imposed"]
        assert total["fx_N"] == pytest.approx(-w * self.HEIGHT, rel=1e-5)
        assert abs(total["my_Nm"]) == pytest.approx(w * self.HEIGHT**2 / 2, rel=1e-5)

    def test_turned_off_the_global_axes(self, tmp_path):
        (tmp_path / "flat").mkdir()
        (tmp_path / "turned").mkdir()
        flat, _ = self._run(tmp_path / "flat", 0.0)
        turned, warnings = self._run(tmp_path / "turned", 30.0)
        (warning,) = [w for w in warnings if PLANE_WARNING in w]
        assert "every node is held across the plane" in warning
        before = flat["global_displacements"]["envelope"]
        after = turned["global_displacements"]["envelope"]
        angle = math.radians(30.0)
        # The mesh of a surface is not the same after the move
        assert after["max_displacement_m"] == pytest.approx(
            before["max_displacement_m"], rel=1e-3
        )
        assert after["max_tx_m"] == pytest.approx(
            before["max_tx_m"] * math.cos(angle), rel=1e-3
        )
        assert after["max_ty_m"] == pytest.approx(
            before["max_tx_m"] * math.sin(angle), rel=1e-3
        )
        total = turned["global_reactions"]["by_load_case"]["Imposed"]
        assert math.hypot(total["fx_N"], total["fy_N"]) == pytest.approx(
            self._push() * self.HEIGHT, rel=1e-5
        )


class TestPointLoadAtAFreeEnd:
    """A 3 m column, 0.1 m square, 10 kN down on its top (aiz.76).

    CalculiX put the force on the four corners of the expanded top face, a
    quarter each, and dented them: 2.7 % more shortening than PL/EA at a
    0.25 m mesh and 6.6 % at 0.1 m. The top is now a knot.
    """

    @pytest.mark.parametrize("mesh_size", [0.5, 0.1])
    def test_shortening_is_pl_over_ea_at_any_mesh(self, tmp_path, mesh_size):
        data, _ = _plane_run(
            tmp_path,
            mesh_size=mesh_size,
            nodes={"A": (0, 0), "B": (0, 3)},
            members=[("A", "B")],
            supports={"A": PLANE_FIXED},
            loads={"B": (0.0, -10000.0)},
            hinged=False,
        )
        expected = 10000.0 * 3.0 / (PLANE_E * 0.01)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(expected, rel=1e-3)


class TestBeamOnTwoDimensionalSupports:
    """A 4 m beam on a pin and a roller that hold X and Z only, 10 kN at midspan.

    It can slide and swing across its plane and turn about its own axis. The
    two members it is made of each count as held in torsion by the other, so
    nothing was done about it and nothing was said: 8.5 mm of deflection for
    7.6, and 5.7 mm across its plane.
    """

    def test_deflection_and_moment(self, tmp_path):
        data, warnings = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (2, 0), "C": (4, 0)},
            members=[("A", "B"), ("B", "C")],
            supports={"A": PLANE_PIN_2D, "C": PLANE_ROLLER_2D},
            loads={"B": (0.0, -10000.0)},
            hinged=False,
            mesh_size=0.25,
        )
        assert [w for w in warnings if PLANE_WARNING in w]
        stiffness = PLANE_E * 0.1**4 / 12
        shear = PLANE_E / 2.6 * 0.01 * 5 / 6
        expected = 10000.0 * 4.0**3 / (48 * stiffness) + 10000.0 * 4.0 / (4 * shear)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(expected, rel=0.01)
        assert envelope.get("max_ty_m", 0.0) < 0.001 * envelope["max_tz_m"]
        for member in data["members"]:
            assert member["envelope"]["section_forces"]["max_Mf2_Nm"] == pytest.approx(
                10000.0, rel=FORCE_TOLERANCE
            )


class TestDeflectedShape:
    """The deflected shape of a member along it (``94g.13.2``).

    A 4 m cantilever along X, 0.1 m square, clamped at A, of two members
    meeting at M halfway. The displacements and rotations of its axis are
    those of Timoshenko's beam at every cross-section.
    """

    LOAD, LENGTH, SIDE, TWIST = 1000.0, 4.0, 0.1, 200.0
    KEYS = {"distance_m", "ux_m", "uy_m", "uz_m", "rx_rad", "ry_rad", "rz_rad"}

    def _shapes(self, tmp_path, moments=None):
        """``[(x of the member's start, its shape)]`` for the case ``Load``."""
        data, _ = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "M": (2, 0), "B": (4, 0)},
            members=[("A", "M"), ("M", "B")],
            supports={"A": PLANE_FIXED},
            loads={"B": (0.0, -self.LOAD)},
            moments=moments,
            hinged=False,
            mesh_size=0.25,
        )
        names = _member_names(str(tmp_path / "plane.ifc"))
        starts = {"AM": 0.0, "MB": 2.0}
        return [
            (starts[names[m["ifc_guid"]]], m["deflected_shapes"]["Load"])
            for m in data["members"]
        ]

    def test_bending_and_shear_along_it(self, tmp_path):
        bending = PLANE_E * self.SIDE**4 / 12
        shear = PLANE_E / 2.6 * self.SIDE**2 * 5 / 6
        found = 0
        for start, shape in self._shapes(tmp_path):
            assert set(shape) == self.KEYS
            assert shape["distance_m"] == sorted(shape["distance_m"])
            for i, distance in enumerate(shape["distance_m"]):
                x = start + distance
                deflection = (
                    self.LOAD * x**2 * (3 * self.LENGTH - x) / (6 * bending)
                    + self.LOAD * x / shear
                )
                # Shear moves the axis and does not turn the sections
                slope = self.LOAD * x * (2 * self.LENGTH - x) / (2 * bending)
                assert shape["uz_m"][i] == pytest.approx(
                    -deflection, rel=0.005, abs=1e-7
                )
                assert shape["ry_rad"][i] == pytest.approx(slope, rel=0.005, abs=1e-7)
                for key in ("ux_m", "uy_m", "rx_rad", "rz_rad"):
                    assert abs(shape[key][i]) < 1e-3 * max(deflection, 1e-6), key
                found += 1
        # Both ends and the middle of every 0.25 m element, each once
        assert found == 2 * (2 * 8 + 1)

    def test_connections_move_with_it(self, tmp_path):
        """The clamp, the joint and the tip, and what an IFC export needs.

        Each point connection has the translation and rotation of the
        members' axis there (94g.13.3).
        """
        self._shapes(tmp_path)
        with open(tmp_path / "out" / "results.json") as fh:
            data = json.load(fh)
        bending = PLANE_E * self.SIDE**4 / 12
        shear = PLANE_E / 2.6 * self.SIDE**2 * 5 / 6
        model = ifcopenshell.open(str(tmp_path / "plane.ifc"))
        names = {c.GlobalId: c.Name for c in model.by_type("IfcStructuralConnection")}
        found = {}
        for connection in data["connections"]:
            found[names[connection["ifc_guid"]]] = connection["by_load_case"]["Load"]
        assert sorted(found) == ["A", "B", "M"]
        for name, x in (("A", 0.0), ("M", 2.0), ("B", 4.0)):
            deflection = (
                self.LOAD * x**2 * (3 * self.LENGTH - x) / (6 * bending)
                + self.LOAD * x / shear
            )
            slope = self.LOAD * x * (2 * self.LENGTH - x) / (2 * bending)
            ux, uy, uz = found[name]["translation_m"]
            rx, ry, rz = found[name]["rotation_rad"]
            assert uz == pytest.approx(-deflection, rel=1e-3, abs=1e-9), name
            assert ry == pytest.approx(slope, rel=1e-3, abs=1e-9), name
            assert max(abs(ux), abs(uy), abs(rx), abs(rz)) < 1e-9 + 1e-4 * deflection

        (case,) = model.by_type("IfcStructuralLoadCase")
        assert data["load_case_ifc_guids"] == {"Load": case.GlobalId}
        assert data["ifc_result_group"] == {
            "theory_type": "FIRST_ORDER_THEORY",
            "is_linear": True,
        }

    def test_twist_along_it(self, tmp_path):
        """A torque at the tip as well: the sections turn by T x / GJ."""
        torsion = PLANE_E / 2.6 * 0.1406 * self.SIDE**4
        for start, shape in self._shapes(
            tmp_path, moments={"B": (self.TWIST, 0.0, 0.0)}
        ):
            for distance, twist in zip(shape["distance_m"], shape["rx_rad"]):
                assert twist == pytest.approx(
                    self.TWIST * (start + distance) / torsion, rel=0.005, abs=1e-8
                )


class TestStraightRunFreeToSpin:
    """A 4 m beam of two members on ball supports, loaded down and across.

    Not a plane structure, since it is loaded both ways. Nothing holds it
    against turning about its own axis, and each member used to count as held
    in torsion by the other: 13.0 mm of deflection for 7.6 and 9.2 mm across
    for 3.8, with no warning (``aiz.72``).
    """

    DOWN, ACROSS, SIDE = 10000.0, 5000.0, 0.1

    def _deflection(self, load: float, span: float = 4.0) -> float:
        stiffness = PLANE_E * self.SIDE**4 / 12
        shear = PLANE_E / 2.6 * self.SIDE**2 * 5 / 6
        return load * span**3 / (48 * stiffness) + load * span / (4 * shear)

    def _check(self, data, warnings, members: int) -> None:
        (warning,) = [w for w in warnings if "free to spin" in w]
        assert f"{members} member(s) are free to spin about their own axis" in warning
        assert "held in torsion at one of its supports" in warning
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(
            self._deflection(self.DOWN), rel=0.01
        )
        assert envelope["max_ty_m"] == pytest.approx(
            self._deflection(self.ACROSS), rel=0.01
        )
        for member in data["members"]:
            assert member["envelope"]["section_forces"]["max_T_Nm"] < 1.0

    def test_supports_at_its_ends(self, tmp_path):
        data, warnings = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (2, 0), "C": (4, 0)},
            members=[("A", "B"), ("B", "C")],
            supports={"A": PLANE_PIN, "C": PLANE_ROLLER},
            loads={"B": (0.0, -self.DOWN)},
            load_y=self.ACROSS,
            hinged=False,
            mesh_size=0.25,
        )
        self._check(data, warnings, members=2)

    def test_supports_at_joints_inside_it(self, tmp_path):
        """With a metre overhanging each support: held where two members meet."""
        data, warnings = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (1, 0), "M": (3, 0), "C": (5, 0), "D": (6, 0)},
            members=[("A", "B"), ("B", "M"), ("M", "C"), ("C", "D")],
            supports={"B": PLANE_PIN, "C": PLANE_ROLLER},
            loads={"M": (0.0, -self.DOWN)},
            load_y=self.ACROSS,
            hinged=False,
            mesh_size=0.25,
        )
        self._check(data, warnings, members=4)


class TestInclinedBeamFreeToSpin:
    """A 5 m rafter rising 3 in 4, two members on ball supports.

    10 kN down and 5 kN across its plane at the joint. It can turn about its
    own axis, which is no global one, so no rotation of a node could be
    restrained to stop it: it was reported and left, and came out with 9.79 mm
    down for 9.54 and 7.76 mm across for 7.45. The support at its foot now
    holds that rotation with a stiff arm (``aiz.74``).
    """

    DOWN, ACROSS, SIDE, LENGTH = 10000.0, 5000.0, 0.1, 5.0

    def _deflection(self, load: float) -> float:
        stiffness = PLANE_E * self.SIDE**4 / 12
        shear = PLANE_E / 2.6 * self.SIDE**2 * 5 / 6
        return load * self.LENGTH**3 / (48 * stiffness) + load * self.LENGTH / (
            4 * shear
        )

    def _rafter(self, tmp_path):
        return _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (2, 1.5), "C": (4, 3)},
            members=[("A", "B"), ("B", "C")],
            supports={"A": PLANE_PIN, "C": PLANE_PIN},
            loads={"B": (0.0, -self.DOWN)},
            load_y=self.ACROSS,
            hinged=False,
            mesh_size=0.25,
        )

    def test_deflection(self, tmp_path):
        """The part of the load across the rafter bends it; the rest is axial."""
        data, warnings = self._rafter(tmp_path)
        (warning,) = [w for w in warnings if "free to spin" in w]
        assert "2 member(s) are free to spin about their own axis" in warning
        assert "held in torsion at one of its supports" in warning
        across_the_rafter = self._deflection(0.8 * self.DOWN)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(0.8 * across_the_rafter, rel=0.01)
        assert envelope["max_tx_m"] == pytest.approx(0.6 * across_the_rafter, rel=0.01)
        assert envelope["max_ty_m"] == pytest.approx(
            self._deflection(self.ACROSS), rel=0.01
        )

    def test_forces_and_reactions(self, tmp_path):
        """The hold carries nothing: no torsion, and the reactions of statics."""
        data, _ = self._rafter(tmp_path)
        for member in data["members"]:
            forces = member["envelope"]["section_forces"]
            assert forces["max_T_Nm"] < 1.0
            assert forces["max_Mf2_Nm"] == pytest.approx(
                0.8 * self.DOWN * self.LENGTH / 4, rel=FORCE_TOLERANCE
            )
            assert forces["max_Mf1_Nm"] == pytest.approx(
                self.ACROSS * self.LENGTH / 4, rel=FORCE_TOLERANCE
            )
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["fz_N"] == pytest.approx(self.DOWN, rel=1e-5)
        assert total["fy_N"] == pytest.approx(-self.ACROSS, rel=1e-5)
        assert abs(total["fx_N"]) < 1e-5 * self.DOWN
        for x, z in ((0.0, 0.0), (4.0, 3.0)):
            reaction = _support_at(data, (x, 0.0, z))["by_load_case"]["Load"]
            assert reaction["fy_N"] == pytest.approx(-self.ACROSS / 2, rel=1e-3)
            assert reaction["fz_N"] == pytest.approx(self.DOWN / 2, rel=0.01)


class TestBeamTurningWithAnArmAcross:
    """A 4 m beam along X on ball supports, a 3 m arm out along Y from its end.

    1 kN down at the tip of the arm. The arm joins the beam rigidly and
    across it, so the beam once counted as held in torsion by it; but the arm
    has no support and swings with the beam about the line of the two balls,
    a mechanism (``aiz.79``): it came out with 7480 km of deflection and
    reactions of 148 and 493 N. Held at the far support, the beam carries
    3 m x 1 kN of torsion to it: the tip drops by the twist of the beam times
    3 m, and the arm's own bending and shear as a cantilever.
    """

    LOAD, BEAM, ARM, SIDE = 1000.0, 4.0, 3.0, 0.1

    def test_held_and_carried_in_torsion(self, tmp_path):
        data, warnings = _plane_run(
            tmp_path,
            nodes={"A": (0, 0, 0), "B": (self.BEAM, 0, 0), "D": (self.BEAM, 3, 0)},
            members=[("A", "B"), ("B", "D")],
            supports={"A": PLANE_PIN, "B": PLANE_PIN},
            loads={"D": (0.0, -self.LOAD)},
            hinged=False,
            mesh_size=0.25,
        )
        (warning,) = [w for w in warnings if "free to spin" in w]
        assert "1 member(s) are free to spin about their own axis" in warning
        assert "held in torsion at one of its supports" in warning

        torque = self.LOAD * self.ARM
        far = _support_at(data, (0.0, 0.0, 0.0))
        # The hold is the support's, so its moment is in the reactions
        assert far["restrained"] == ["tx", "ty", "tz", "rx"]
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["imbalance_N"] < 1e-6 * self.LOAD
        assert total["moment_imbalance_Nm"] < 1e-6 * torque
        assert abs(far["by_load_case"]["Load"]["mx_Nm"]) == pytest.approx(
            torque, rel=1e-3
        )
        assert abs(far["by_load_case"]["Load"]["fz_N"]) < 1e-3 * self.LOAD
        near = _support_at(data, (self.BEAM, 0.0, 0.0))["by_load_case"]["Load"]
        assert near["fz_N"] == pytest.approx(self.LOAD, rel=1e-4)
        torsions = sorted(
            m["envelope"]["section_forces"]["max_T_Nm"] for m in data["members"]
        )
        assert torsions[0] < 1.0
        assert torsions[1] == pytest.approx(torque, rel=FORCE_TOLERANCE)

        shear_modulus = PLANE_E / 2.6
        torsion_constant = 0.1406 * self.SIDE**4
        twist = torque * self.BEAM / (shear_modulus * torsion_constant)
        bending = self.LOAD * self.ARM**3 / (3 * PLANE_E * self.SIDE**4 / 12)
        shear = self.LOAD * self.ARM / (shear_modulus * self.SIDE**2 * 5 / 6)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(
            twist * self.ARM + bending + shear, rel=0.01
        )


class TestBeamEndingOnTheSpanOfAnother:
    """A 3 m beam between the middles of two fixed 4 m girders, 10 kN on it.

    The file gives the ends of the beam connections of their own, which join
    nothing else, as ``building_02`` does for its secondary beams. The mesh
    has one node where the beam meets a girder, so they are joined rigidly:
    the beam twists the girders and is held by them. It was reported as free
    to spin about its own axis, which it is not (``aiz.80``), and the joint
    the file does not have was not reported at all.
    """

    LOAD, SPAN = 10000.0, 3.0
    GIRDERS = {"A": (0, 0, 0), "B": (4, 0, 0), "C": (0, 3, 0), "D": (4, 3, 0)}
    BEAM = {"S": (2, 0, 0), "M": (2, 1.5, 0), "T": (2, 3, 0)}

    def _run(self, tmp_path, girders):
        data, warnings = _plane_run(
            tmp_path,
            nodes={**self.GIRDERS, **self.BEAM},
            members=girders + [("S", "M"), ("M", "T")],
            supports={name: PLANE_FIXED for name in self.GIRDERS},
            loads={"M": (0.0, -self.LOAD)},
            hinged=False,
            mesh_size=0.25,
        )
        names = _member_names(str(tmp_path / "plane.ifc"))
        forces = {
            names[member["ifc_guid"]]: member["envelope"]["section_forces"]
            for member in data["members"]
        }
        return data, warnings, forces

    def test_joined_rigidly_and_said_so(self, tmp_path):
        """The moment at the ends of the beam is the torsion of the girders."""
        _, warnings, forces = self._run(tmp_path, [("A", "B"), ("C", "D")])
        (warning,) = [w for w in warnings if "no connection between them" in w]
        assert "Curve members touch at 2 place(s)" in warning
        assert not [w for w in warnings if "free to spin" in w]

        torsion = forces["AB"]["max_T_Nm"]
        assert torsion > 0.1 * self.LOAD * self.SPAN / 4
        assert forces["CD"]["max_T_Nm"] == pytest.approx(torsion, rel=1e-3)
        for name in ("SM", "MT"):
            bending = max(forces[name]["max_Mf1_Nm"], forces[name]["max_Mf2_Nm"])
            assert bending == pytest.approx(
                self.LOAD * self.SPAN / 4 - 2 * torsion, rel=FORCE_TOLERANCE
            )
            assert forces[name]["max_T_Nm"] < 1.0

    def test_as_with_the_joints_in_the_file(self, tmp_path):
        """Girders made of two members each, joined to the beam where it ends."""
        (tmp_path / "mesh").mkdir()
        (tmp_path / "file").mkdir()
        mesh, _, mesh_forces = self._run(tmp_path / "mesh", [("A", "B"), ("C", "D")])
        file, warnings, file_forces = self._run(
            tmp_path / "file", [("A", "S"), ("S", "B"), ("C", "T"), ("T", "D")]
        )
        assert not [w for w in warnings if "no connection between them" in w]
        assert not [w for w in warnings if "free to spin" in w]
        assert mesh["global_displacements"]["envelope"]["max_tz_m"] == pytest.approx(
            file["global_displacements"]["envelope"]["max_tz_m"], rel=1e-4
        )
        assert mesh_forces["AB"]["max_T_Nm"] == pytest.approx(
            file_forces["AS"]["max_T_Nm"], rel=1e-3
        )
        for key in ("max_Mf1_Nm", "max_Mf2_Nm"):
            assert mesh_forces["SM"][key] == pytest.approx(
                file_forces["SM"][key], rel=1e-3, abs=1.0
            )


class TestPlaneFrameJoinedByTheMesh:
    """A beam framing into the span of two fixed columns, 10 kN on it.

    Columns 4 m high and 4 m apart, the beam between them at 3 m. The file
    gives the ends of the beam connections of their own, which join nothing
    else; the mesh joins it to the columns rigidly. The frame stands up out
    of its plane on its fixed feet, and was once held in it all the same,
    since the plane check went by the file's connections alone (``aiz.81``).
    """

    NODES = {
        "A": (0, 0),
        "B": (0, 4),
        "C": (4, 4),
        "D": (4, 0),
        "E": (0, 3),
        "F": (4, 3),
        "M": (2, 3),
    }

    def _run(self, tmp_path, columns):
        return _plane_run(
            tmp_path,
            nodes=self.NODES,
            members=columns + [("E", "M"), ("M", "F")],
            supports={"A": PLANE_FIXED, "D": PLANE_FIXED},
            loads={"M": (0.0, -10000.0)},
            hinged=False,
            mesh_size=0.25,
        )

    def test_not_held_in_its_plane(self, tmp_path):
        (tmp_path / "mesh").mkdir()
        (tmp_path / "file").mkdir()
        mesh, warnings = self._run(tmp_path / "mesh", [("A", "B"), ("D", "C")])
        assert [w for w in warnings if "no connection between them" in w]
        assert not [w for w in warnings if PLANE_WARNING in w]
        assert not [w for w in warnings if "free to spin" in w]
        file, warnings = self._run(
            tmp_path / "file", [("A", "E"), ("E", "B"), ("D", "F"), ("F", "C")]
        )
        assert not [w for w in warnings if PLANE_WARNING in w]
        assert mesh["global_displacements"]["envelope"]["max_tz_m"] == pytest.approx(
            file["global_displacements"]["envelope"]["max_tz_m"], rel=1e-4
        )


class TestBeamContinuousOverASupport:
    """Two 4 m spans over three pinned supports, 10 kN in the middle of each.

    The members meet at the middle support with no release, so the beam runs
    on over it: 3 P L / 16 there, 5 P L / 32 under the loads, and 5 P / 16 and
    11 P / 8 on the supports. A support that leaves rotations free used to
    hinge every member meeting at it, which made this two simply supported
    beams: no moment over the support, P L / 4 under the loads and 8.0 mm of
    deflection for 3.4 (``aiz.78``).
    """

    LOAD, SPAN = 10000.0, 4.0

    def _beam(self, tmp_path):
        data, _ = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "M": (2, 0), "B": (4, 0), "N": (6, 0), "C": (8, 0)},
            members=[("A", "M"), ("M", "B"), ("B", "N"), ("N", "C")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER, "C": PLANE_ROLLER},
            loads={"M": (0.0, -self.LOAD), "N": (0.0, -self.LOAD)},
            hinged=False,
            mesh_size=0.25,
        )
        return data

    def test_moments(self, tmp_path):
        data = self._beam(tmp_path)
        names = _member_names(str(tmp_path / "plane.ifc"))
        moments = {
            names[m["ifc_guid"]]: m["section_force_diagrams"]["Load"]["Mf2_Nm"]
            for m in data["members"]
        }
        over_support = 3 * self.LOAD * self.SPAN / 16
        under_load = 5 * self.LOAD * self.SPAN / 32
        assert abs(moments["MB"][-1]) == pytest.approx(over_support, rel=0.01)
        assert abs(moments["BN"][0]) == pytest.approx(over_support, rel=0.01)
        assert moments["MB"][-1] * moments["MB"][0] < 0
        assert abs(moments["AM"][-1]) == pytest.approx(under_load, rel=0.01)
        assert abs(moments["NC"][0]) == pytest.approx(under_load, rel=0.01)
        assert abs(moments["AM"][0]) < 0.01 * under_load

    def test_reactions(self, tmp_path):
        data = self._beam(tmp_path)
        for x, share in ((0.0, 5 / 16), (4.0, 11 / 8), (8.0, 5 / 16)):
            support = _support_at(data, (x, 0.0, 0.0))
            assert support["by_load_case"]["Load"]["fz_N"] == pytest.approx(
                share * self.LOAD, rel=0.01
            )


INCLINE = math.radians(30.0)
# A support on a plane that rises along X: z is its normal, x runs up it
ON_AN_INCLINE = (
    (-math.sin(INCLINE), 0.0, math.cos(INCLINE)),
    (math.cos(INCLINE), 0.0, math.sin(INCLINE)),
)


class TestSkewSupports:
    """Supports whose axes are not the global ones (``aiz.35``).

    A 4 m beam of 0.1 m square section along X, 10 kN at midspan. Such a
    support used to be analysed as if its axes were global, with a warning.
    """

    LOAD, SPAN = 10000.0, 4.0

    def _beam(self, tmp_path, supports, support_axes):
        data, _ = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (2, 0), "C": (4, 0)},
            members=[("A", "B"), ("B", "C")],
            supports=supports,
            loads={"B": (0.0, -self.LOAD)},
            hinged=False,
            mesh_size=0.25,
            support_axes=support_axes,
        )
        return data

    @pytest.mark.parametrize(
        "pin, roller",
        [(PLANE_PIN, PLANE_ROLLER), (PLANE_PIN_2D, PLANE_ROLLER_2D)],
        ids=["held across the plane", "as a textbook draws it"],
    )
    def test_roller_on_an_incline(self, tmp_path, pin, roller):
        """Its reaction is normal to the incline: P / (2 cos a), by statics.

        The pin takes the part of it along the beam, which is in compression.
        """
        data = self._beam(tmp_path, {"A": pin, "C": roller}, {"C": ON_AN_INCLINE})
        normal = self.LOAD / (2.0 * math.cos(INCLINE))
        along = normal * math.sin(INCLINE)

        on_incline = _support_at(data, (4.0, 0.0, 0.0))
        assert "tz" in on_incline["restrained_in_axes"]
        assert "tx" not in on_incline["restrained_in_axes"]
        assert "tz" not in on_incline["restrained"]
        in_axes = on_incline["by_load_case_in_axes"]["Load"]
        assert in_axes["fz_N"] == pytest.approx(normal, rel=1e-4)
        assert abs(in_axes["fx_N"]) < 1e-4 * normal
        reaction = on_incline["by_load_case"]["Load"]
        assert reaction["fx_N"] == pytest.approx(-along, rel=1e-4)
        assert reaction["fz_N"] == pytest.approx(self.LOAD / 2.0, rel=1e-4)

        pinned = _support_at(data, (0.0, 0.0, 0.0))["by_load_case"]["Load"]
        assert pinned["fx_N"] == pytest.approx(along, rel=1e-4)
        assert pinned["fz_N"] == pytest.approx(self.LOAD / 2.0, rel=1e-4)
        for member in data["members"]:
            forces = member["envelope"]["section_forces"]
            assert forces["max_compression_N"] == pytest.approx(
                along, rel=FORCE_TOLERANCE
            )
            assert forces["max_Mf2_Nm"] == pytest.approx(
                self.LOAD * self.SPAN / 4.0, rel=FORCE_TOLERANCE
            )
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["imbalance_N"] < 1e-6 * self.LOAD

    def test_rotation_held_about_a_skew_axis(self, tmp_path):
        """One end is clamped about an axis halfway between Y and Z.

        The support's y is that axis and its z the one across it, both at 45
        degrees to the load. Across y the beam is clamped at that end and
        pinned at the other (a propped cantilever under P cos 45); across z
        it is simply supported (under P sin 45). The section is square, so
        the two do not interact.
        """
        half = 0.5**0.5
        data = self._beam(
            tmp_path,
            {"A": (True, True, True, True, True, False), "C": PLANE_PIN},
            {"A": ((0.0, -half, half), (1.0, 0.0, 0.0))},
        )
        part = self.LOAD * half

        clamped = _support_at(data, (0.0, 0.0, 0.0))
        assert clamped["restrained"] == ["tx", "ty", "tz", "rx"]
        assert clamped["restrained_in_axes"] == ["tx", "ty", "tz", "rx", "ry"]
        assert clamped["moments"] in MOMENT_SOURCES
        in_axes = clamped["by_load_case_in_axes"]["Load"]
        assert in_axes["fy_N"] == pytest.approx(part / 2.0, rel=FORCE_TOLERANCE)
        assert in_axes["fz_N"] == pytest.approx(part * 11.0 / 16.0, rel=0.01)
        assert abs(in_axes["my_Nm"]) == pytest.approx(
            part * self.SPAN * 3.0 / 16.0, rel=0.02
        )
        assert abs(in_axes["mz_Nm"]) < 1e-3 * abs(in_axes["my_Nm"])

        # At the other end: 5/16 of one part and half of the other
        pinned = _support_at(data, (4.0, 0.0, 0.0))["by_load_case"]["Load"]
        assert pinned["fz_N"] == pytest.approx(
            half * part * (5.0 / 16.0 + 0.5), rel=0.01
        )
        assert pinned["fy_N"] == pytest.approx(
            half * part * (0.5 - 5.0 / 16.0), rel=0.02
        )
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["imbalance_N"] < 1e-6 * self.LOAD

        stiffness = PLANE_E * 0.1**4 / 12
        simply = self.LOAD * self.SPAN**3 / (48 * stiffness)
        propped = 7.0 * self.LOAD * self.SPAN**3 / (768 * stiffness)
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx((simply + propped) / 2, rel=0.02)
        assert envelope["max_ty_m"] == pytest.approx((simply - propped) / 2, rel=0.05)

    def test_clamp_that_slides_on_an_incline(self, tmp_path):
        """A free translation and skew rotations at one support (``aiz.75``).

        The end at C slides up and down the incline and is held in every
        rotation but the one about the incline's normal, so the arm that
        holds its rotations is tied to the node, whose own translations are
        tied by an equation. A is a vertical roller and B has P s along the
        beam as well as P down, s and c the sine and cosine of the incline.

        Statically determinate: the incline pushes P along its normal, A
        carries P (1 - c), C a moment P L (c - 1/2), and B-C is in
        compression P s. The beam is a cantilever from C, which slides until
        A is back at its height: up the incline by -w_A / s, w_A being the
        cantilever's deflection at A under P (1 - c) there and P at B.
        """
        s, c = math.sin(INCLINE), math.cos(INCLINE)
        data, _ = _plane_run(
            tmp_path,
            nodes={"A": (0, 0), "B": (2, 0), "C": (4, 0)},
            members=[("A", "B"), ("B", "C")],
            supports={
                "A": PLANE_ROLLER,
                "C": (False, True, True, True, True, False),
            },
            loads={"B": (self.LOAD * s, -self.LOAD)},
            hinged=False,
            mesh_size=0.25,
            support_axes={"C": ON_AN_INCLINE},
        )
        load, span = self.LOAD, self.SPAN

        sliding = _support_at(data, (span, 0.0, 0.0))
        assert sliding["restrained_in_axes"] == ["ty", "tz", "rx", "ry"]
        assert sliding["moments"] in MOMENT_SOURCES
        in_axes = sliding["by_load_case_in_axes"]["Load"]
        assert in_axes["fz_N"] == pytest.approx(load, rel=1e-4)
        assert abs(in_axes["fx_N"]) < 1e-4 * load
        assert abs(in_axes["my_Nm"]) == pytest.approx(
            load * span * (c - 0.5), rel=FORCE_TOLERANCE
        )
        reaction = sliding["by_load_case"]["Load"]
        assert reaction["fx_N"] == pytest.approx(-load * s, rel=1e-4)
        assert reaction["fz_N"] == pytest.approx(load * c, rel=1e-4)

        roller = _support_at(data, (0.0, 0.0, 0.0))["by_load_case"]["Load"]
        assert roller["fz_N"] == pytest.approx(load * (1 - c), rel=1e-4)
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["imbalance_N"] < 1e-6 * load

        forces = [m["envelope"]["section_forces"] for m in data["members"]]
        assert max(f["max_compression_N"] for f in forces) == pytest.approx(
            load * s, rel=FORCE_TOLERANCE
        )
        assert max(f["max_Mf2_Nm"] for f in forces) == pytest.approx(
            load * span * (c - 0.5), rel=FORCE_TOLERANCE
        )

        stiffness = PLANE_E * 0.1**4 / 12
        at_a = (1 - c) / 3 - 5.0 / 48.0  # w_A in P L^3 / EI, upwards
        rise = -at_a * load * span**3 / stiffness
        # Read where the beam does not turn, so on no face of it
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tz_m"] == pytest.approx(rise, rel=0.01)

    def test_line_support_on_a_tilted_slab(self, tmp_path):
        """slab_01 tilted by 30 degrees about X under its weight.

        Its edges and the normals of its supports are then skew, and every
        node of the edges is of shells alone, whose rotation about the
        normal is held through the arm too. The weight w has w cos 30 across
        the slab, which the edges carry as they do the whole of it when the
        slab is level, and w sin 30 down the slope, along the edges, half
        on each.
        """
        angle = math.radians(30.0)
        runs = {
            "level": SLAB,
            "tilted": _placed_variant(
                tmp_path,
                "slab_01",
                z_axis=(0.0, -math.sin(angle), math.cos(angle)),
            ),
        }
        level, tilted = (
            _run(path, tmp_path / label, mesh_size=0.25, gravity=True)
            for label, path in runs.items()
        )

        weight = level["global_reactions"]["by_load_case"]["Gravity"]["fz_N"]
        total = tilted["global_reactions"]["by_load_case"]["Gravity"]
        assert total["fz_N"] == pytest.approx(weight, rel=1e-6)
        assert total["imbalance_N"] < 1e-6 * weight

        before = level["global_displacements"]["envelope"]["max_displacement_m"]
        after = tilted["global_displacements"]["envelope"]["max_displacement_m"]
        assert after == pytest.approx(before * math.cos(angle), rel=0.005)

        assert len(tilted["supports"]) == len(level["supports"]) == 2
        for original, moved in zip(level["supports"], tilted["supports"]):
            assert moved["restrained_in_axes"] == original.get(
                "restrained_in_axes", original["restrained"]
            )
            expected = original.get("by_load_case_in_axes", original["by_load_case"])
            found = moved["by_load_case_in_axes"]["Gravity"]
            assert found["fz_N"] == pytest.approx(
                expected["Gravity"]["fz_N"] * math.cos(angle), rel=1e-3
            )
            assert abs(found["fx_N"]) == pytest.approx(
                weight * math.sin(angle) / 2, rel=1e-3
            )

    def test_tilted_slab_pushed_in_its_plane(self, tmp_path):
        """slab_01 between two pinned edges, 10 kPa in its plane along them.

        Tilted 30 degrees about X, the hold along each edge is an equation
        on nodes of shells alone, which holds the mean of the top and bottom
        of the expanded section and not its middle unless the node is a knot
        (``aiz.103``). It was 3 % more flexible than the level slab at this
        mesh, and more on a finer one.
        """
        import ifcopenshell

        angle = math.radians(30.0)
        found = {}
        for label, turn in (("level", 0.0), ("tilted", angle)):
            model = ifcopenshell.open(SLAB)
            for rel in model.by_type("IfcRelConnectsStructuralMember"):
                rel.AppliedCondition = None
            for edge in model.by_type("IfcStructuralCurveConnection"):
                edge.AppliedCondition = _edge_condition(
                    model, (True, True, True, False, False, False)
                )
            slab = model.by_type("IfcStructuralSurfaceMember")[0]
            for action in list(model.by_type("IfcStructuralAction")):
                for rel in model.get_inverse(action):
                    if rel.is_a("IfcRelConnectsStructuralActivity"):
                        model.remove(rel)
                model.remove(action)
            _add_area_load(model, slab, (0.0, 1.0e4, 0.0))
            placement = model.create_entity(
                "IfcLocalPlacement",
                RelativePlacement=model.create_entity(
                    "IfcAxis2Placement3D",
                    Location=model.create_entity("IfcCartesianPoint", (0.0, 0.0, 0.0)),
                    Axis=model.create_entity(
                        "IfcDirection", (0.0, -math.sin(turn), math.cos(turn))
                    ),
                    RefDirection=model.create_entity("IfcDirection", (1.0, 0.0, 0.0)),
                ),
            )
            for kind in ("IfcStructuralItem", "IfcStructuralActivity"):
                for entity in model.by_type(kind):
                    entity.ObjectPlacement = placement
            path = str(tmp_path / f"{label}.ifc")
            model.write(path)
            found[label] = _run(path, tmp_path / label, mesh_size=0.25)

        level, tilted = found["level"], found["tilted"]
        before = level["global_displacements"]["envelope"]["max_displacement_m"]
        after = tilted["global_displacements"]["envelope"]["max_displacement_m"]
        assert after == pytest.approx(before, rel=1e-4)
        case = level["load_cases"][0]
        push = level["global_reactions"]["by_load_case"][case]["fy_N"]
        total = tilted["global_reactions"]["by_load_case"][case]
        assert math.hypot(total["fy_N"], total["fz_N"]) == pytest.approx(
            abs(push), rel=1e-6
        )
        assert total["imbalance_N"] < 1e-6 * abs(push)


def _node_condition(model, values):
    """An IfcBoundaryNodeCondition: True/False for held/free, a number for a spring.

    Numbers are in the file's units: a linear stiffness first three, a
    rotational one last three.
    """
    measures = ["IfcLinearStiffnessMeasure"] * 3 + ["IfcRotationalStiffnessMeasure"] * 3
    return model.create_entity(
        "IfcBoundaryNodeCondition",
        None,
        *[
            model.create_entity(
                "IfcBoolean" if isinstance(value, bool) else measure, value
            )
            for value, measure in zip(values, measures)
        ],
    )


class TestElasticSupports:
    """Supports with a stiffness that is neither zero nor rigid (aiz.94).

    beam_01 is in millimetres and newtons, so the springs are given in N/mm
    and N*mm/rad, which checks their units too.
    """

    B = TestFixedFixedBeamPointLoad
    MESH = 0.25

    def _beam(self, tmp_path, start, end) -> str:
        model = _beam_01()
        supports = sorted(
            model.by_type("IfcStructuralPointConnection"), key=lambda c: c.id()
        )
        for support, values in zip(supports, (start, end)):
            support.AppliedCondition = _node_condition(model, values)
        path = str(tmp_path / "elastic.ifc")
        model.write(path)
        return path

    def test_spring_under_a_beam_end(self, tmp_path):
        """A pin and a vertical spring: the spring takes P / 2 and settles P / 2k."""
        stiffness = 1.0e6  # N/m
        end = (False, True, stiffness / 1000.0, False, False, False)
        data = _run(self._beam(tmp_path, PIN, end), tmp_path, self.MESH)
        load = self.B.LOAD
        assert _max_vertical_deflection(data) == pytest.approx(
            load / 2 / stiffness, rel=1e-3
        )
        sprung = [s for s in data["supports"] if s.get("springs")]
        assert len(sprung) == 1
        (spring,) = sprung[0]["springs"]
        assert spring["stiffness"] == pytest.approx(stiffness)
        assert spring["unit"] == "N/m"
        assert sprung[0]["restrained"] == ["ty"]
        for support in data["supports"]:
            assert support["by_load_case"]["Dead"]["fz_N"] == pytest.approx(
                load / 2, rel=1e-6
            )
        total = data["global_reactions"]["by_load_case"]["Dead"]
        assert total["imbalance_N"] < 1e-6 * load

    def test_rotational_spring_at_a_beam_end(self, tmp_path):
        """A partly fixed end: M = theta0 / (L / 3EI + 1 / k).

        theta0 = P L^2 / 16 EI is the end rotation of the simply supported
        beam under the point load. CalculiX ignores a spring on the rotation
        of a beam node; the spring acts through an arm.
        """
        stiffness = 2.0e7  # N*m/rad
        start = (True, True, True, True, stiffness * 1000.0, True)
        data = _run(
            self._beam(tmp_path, start, (False, True, True, False, False, False)),
            tmp_path,
            self.MESH,
        )
        b = self.B
        bending = b.E * b.INERTIA
        theta0 = b.LOAD * b.LENGTH**2 / (16 * bending)
        moment = theta0 / (b.LENGTH / (3 * bending) + 1 / stiffness)
        held = _support_at(data, (0.0, 0.0, 0.0))
        values = held["by_load_case"]["Dead"]
        assert abs(values["my_Nm"]) == pytest.approx(moment, rel=0.01)
        assert values["fz_N"] == pytest.approx(
            b.LOAD / 2 + abs(values["my_Nm"]) / b.LENGTH, rel=1e-3
        )
        # The solver's forces are kept, and agree with the member's own end
        assert held["forces"] == "solver"
        assert held["moments"] == "solver"
        diagram = _curve_member_diagram(data)
        assert abs(diagram["Mf1_Nm"][0]) == pytest.approx(
            abs(values["my_Nm"]), rel=1e-3
        )
        total = data["global_reactions"]["by_load_case"]["Dead"]
        assert total["imbalance_N"] < 1e-6 * b.LOAD
        assert total["moment_imbalance_Nm"] < 1e-5 * b.LOAD * b.LENGTH


SLAB_E, SLAB_T, SLAB_L, SLAB_W = 2.1e8, 0.2, 5.0, 3.0
SLAB_Q = 5000.0  # N/m²


def _slab_on(tmp_path, condition, corners=None, edges=None) -> str:
    """slab_01 under a uniform load, held by a surface connection or its edges.

    The line connections of the file hold nothing unless ``edges`` (the
    condition both get) is given. ``condition``, when given, is that of a
    surface connection over ``corners`` (the whole slab when left out), as
    (x, y, z): True/False for held/free, a number for a modulus of subgrade
    reaction in N/m³.
    """
    model = ifcopenshell.open(SLAB)
    slab = model.by_type("IfcStructuralSurfaceMember")[0]
    for relation in model.by_type("IfcRelConnectsStructuralMember"):
        relation.AppliedCondition = None
    for connection in model.by_type("IfcStructuralCurveConnection"):
        connection.AppliedCondition = edges(model) if edges else None
    if condition is not None:
        face = slab.Representation.Representations[0].Items[0]
        if corners is not None:
            loop = model.create_entity(
                "IfcPolyLoop",
                [model.create_entity("IfcCartesianPoint", c) for c in corners],
            )
            face = model.create_entity(
                "IfcFaceSurface",
                [model.create_entity("IfcFaceOuterBound", loop, True)],
                face.FaceSurface,
                True,
            )
        context = slab.Representation.Representations[0].ContextOfItems
        shape = model.create_entity(
            "IfcProductDefinitionShape",
            None,
            None,
            [
                model.create_entity(
                    "IfcTopologyRepresentation", context, "Reference", "Face", [face]
                )
            ],
        )
        applied = model.create_entity(
            "IfcBoundaryFaceCondition",
            "ground",
            *[
                model.create_entity(
                    (
                        "IfcBoolean"
                        if isinstance(value, bool)
                        else "IfcModulusOfSubgradeReactionMeasure"
                    ),
                    value,
                )
                for value in condition
            ],
        )
        connection = model.create_entity(
            "IfcStructuralSurfaceConnection",
            ifcopenshell.guid.new(),
            slab.OwnerHistory,
            "ground",
            None,
            None,
            slab.ObjectPlacement,
            shape,
            applied,
        )
        model.create_entity(
            "IfcRelConnectsStructuralMember",
            ifcopenshell.guid.new(),
            slab.OwnerHistory,
            None,
            None,
            slab,
            connection,
        )
        group = model.by_type("IfcRelAssignsToGroup")[0]
        group.RelatedObjects = list(group.RelatedObjects) + [connection]
    _add_area_load(model, slab, (0.0, 0.0, -SLAB_Q))
    path = str(tmp_path / "slab_supports.ifc")
    model.write(path)
    return path


class TestSurfaceSupports:
    """IfcStructuralSurfaceConnection: a slab held over an area (aiz.96)."""

    def test_slab_on_elastic_ground(self, tmp_path):
        """Held in plan and on a modulus k vertically: it settles q / k."""
        modulus = 1.0e7
        data = _run(_slab_on(tmp_path, (True, True, modulus)), tmp_path, mesh_size=0.5)
        (support,) = data["supports"]
        assert support["type"] == "surface"
        assert support["restrained"] == ["tx", "ty"]
        (spring,) = support["springs"]
        assert spring["unit"] == "N/m/m2"
        assert support["position_m"] == pytest.approx([2.5, 1.5, 0.0])
        load = SLAB_Q * SLAB_L * SLAB_W
        assert support["by_load_case"]["Imposed"]["fz_N"] == pytest.approx(
            load, rel=1e-6
        )
        # The springs are lumped as the elements' stiffness is, the load as
        # its work is, so the settlement is not quite even
        assert _max_vertical_deflection(data) == pytest.approx(
            SLAB_Q / modulus, rel=0.02
        )
        total = data["global_reactions"]["by_load_case"]["Imposed"]
        assert total["imbalance_N"] < 1e-6 * load

    def test_slab_held_on_half_its_area(self, tmp_path):
        """The mesh follows the outline; the free half is a cantilever.

        Its tip deflects more than q L^4 / 8 D: a face condition holds the
        translations of the slab's middle surface only, and inside the held
        half its normals turn against transverse shear alone, over a length
        sqrt(D / kappa G t), which adds M l / D at the root.
        """
        half = ((0.0, 0.0, 0.0), (2.5, 0.0, 0.0), (2.5, 3.0, 0.0), (0.0, 3.0, 0.0))
        data = _run(_slab_on(tmp_path, (True, True, True), corners=half), tmp_path, 0.4)
        (support,) = data["supports"]
        assert support["restrained"] == ["tx", "ty", "tz"]
        values = support["by_load_case"]["Imposed"]
        load = SLAB_Q * SLAB_L * SLAB_W
        assert values["fz_N"] == pytest.approx(load, rel=1e-6)
        # The load acts at the middle of the slab, 1.25 m from the support's
        assert abs(values["my_Nm"]) == pytest.approx(load * 1.25, rel=1e-6)

        nu = 0.2
        stiffness = SLAB_E * SLAB_T**3 / (12 * (1 - nu**2))
        length = SLAB_L / 2
        shear = 5.0 / 6.0 * SLAB_E / (2 * (1 + nu)) * SLAB_T
        root = SLAB_Q * length**2 / 2 * math.sqrt(stiffness / shear) / stiffness
        expected = SLAB_Q * length**4 / (8 * stiffness) + root * length
        assert _max_vertical_deflection(data) == pytest.approx(expected, rel=0.03)

    def test_condition_differing_by_direction_needs_a_plane(self, tmp_path):
        model = ifcopenshell.open(_slab_on(tmp_path, (True, True, 1.0e7)))
        (connection,) = model.by_type("IfcStructuralSurfaceConnection")
        face = connection.Representation.Representations[0].Items[0]
        connection.Representation.Representations[0].Items = [
            model.create_entity("IfcFace", face.Bounds)
        ]
        path = str(tmp_path / "no_plane.ifc")
        model.write(path)
        with pytest.raises(ModelExtractionError, match="no plane"):
            analyze_ifc(ifc_path=path, output_dir=str(tmp_path / "out"))

    def test_slab_edges_on_springs(self, tmp_path):
        """Both edges on vertical and rotational springs per metre.

        The slab spans 5 m between them as a strip: settlement q L / 2 k_z,
        and end moments theta0 / (L / 2 D + 1 / k_r) per metre, with
        theta0 = q L^3 / 24 D. Its sides are free, so D is that of a strip
        free to curl, E t^3 / 12. The edge nodes belong to shells alone,
        which have no rotation about their normal: the arm of the rotational
        spring is held against it.
        """
        linear, rotational = 1.0e6, 2.0e5

        def edges(model):
            return model.create_entity(
                "IfcBoundaryEdgeCondition",
                None,
                model.create_entity("IfcBoolean", True),
                model.create_entity("IfcBoolean", True),
                model.create_entity(
                    "IfcModulusOfLinearSubgradeReactionMeasure", linear
                ),
                model.create_entity(
                    "IfcModulusOfRotationalSubgradeReactionMeasure", rotational
                ),
                model.create_entity("IfcBoolean", False),
                model.create_entity("IfcBoolean", False),
            )

        data = _run(_slab_on(tmp_path, None, edges=edges), tmp_path, 0.25)
        stiffness = SLAB_E * SLAB_T**3 / 12
        theta0 = SLAB_Q * SLAB_L**3 / (24 * stiffness)
        moment = theta0 / (SLAB_L / (2 * stiffness) + 1 / rotational)
        assert len(data["supports"]) == 2
        for support in data["supports"]:
            assert support["type"] == "line"
            assert support["moments"] == "springs"
            assert {s["unit"] for s in support["springs"]} == {
                "N/m/m",
                "N*m/rad/m",
            }
            values = support["by_load_case"]["Imposed"]
            assert values["fz_N"] == pytest.approx(
                SLAB_Q * SLAB_L * SLAB_W / 2, rel=1e-4
            )
            assert abs(values["my_Nm"]) == pytest.approx(moment * SLAB_W, rel=0.01)
        total = data["global_reactions"]["by_load_case"]["Imposed"]
        assert total["imbalance_N"] < 1e-6 * SLAB_Q * SLAB_L * SLAB_W


SBB_L, SBB_B, SBB_T = 4.0, 3.0, 0.2
SBB_E, SBB_Q = 3.0e10, 5000.0
SBB_BEAM_B, SBB_BEAM_H = 0.3, 0.5
SBB_OVERHANG = 0.5


def _slab_between_beams(
    tmp_path, released: bool = False, drop: float = 0.0, overhang: float = SBB_OVERHANG
) -> str:
    """Write a slab spanning between two beams it is joined to along line connections.

    The slab is 4 m along x, spans 3 m along y and is 0.2 m thick, at z = 0,
    with nu = 0 and free at x = 0 and x = 4, so that it bends as a strip. The
    beams run along its long edges, ``drop`` below them and ``overhang`` past
    its ends, clamped at both ends and a thousand times as stiff as the slab's
    material: the edges of the slab do not move, and they turn only as the
    joint lets them. The supports hold the beams only. Each line
    connection runs along an edge of the slab and joins slab and beam; with
    ``released`` the slab is free to rotate about it. A uniform load acts on
    the slab, in a load case of its own.
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
    analysis = create(
        "IfcStructuralAnalysisModel",
        guid(),
        None,
        "Slab between beams",
        None,
        None,
        "NOTDEFINED",
        axes,
        None,
        None,
        placement,
    )
    create("IfcRelDeclares", guid(), None, None, None, project, [analysis])

    def material(name, modulus):
        made = create("IfcMaterial", name, None, None)
        create(
            "IfcMaterialProperties",
            "Pset_MaterialMechanical",
            None,
            [
                create(
                    "IfcPropertySingleValue",
                    "YoungModulus",
                    None,
                    create("IfcModulusOfElasticityMeasure", modulus),
                    None,
                ),
                create(
                    "IfcPropertySingleValue",
                    "PoissonRatio",
                    None,
                    create("IfcPositiveRatioMeasure", 0.0),
                    None,
                ),
            ],
            made,
        )
        return made

    def vertex(x, y, z=0.0):
        return create(
            "IfcVertexPoint", create("IfcCartesianPoint", (float(x), float(y), z))
        )

    def shape(kind, item):
        topology = create(
            "IfcTopologyRepresentation", context, "Reference", kind, [item]
        )
        return create("IfcProductDefinitionShape", None, None, [topology])

    def connect(member, connection, condition=None):
        create(
            "IfcRelConnectsStructuralMember",
            guid(),
            None,
            None,
            None,
            member,
            connection,
            condition,
            None,
            None,
            None,
        )

    corners = [
        vertex(x, y) for x, y in ((0, 0), (SBB_L, 0), (SBB_L, SBB_B), (0, SBB_B))
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
        SBB_T,
    )
    create(
        "IfcRelAssociatesMaterial",
        guid(),
        None,
        None,
        None,
        [slab],
        material("Slab", SBB_E),
    )
    profile = create(
        "IfcRectangleProfileDef", "AREA", "Beam", None, SBB_BEAM_B, SBB_BEAM_H
    )
    profile_set = create(
        "IfcMaterialProfileSet",
        None,
        None,
        [
            create(
                "IfcMaterialProfile",
                "Beam",
                None,
                material("Stiff", 1000 * SBB_E),
                profile,
                None,
                None,
            )
        ],
        None,
    )
    products, beams = [slab], []
    for y in (0.0, SBB_B):
        beam = create(
            "IfcStructuralCurveMember",
            guid(),
            None,
            "Beam",
            None,
            None,
            placement,
            shape(
                "Edge",
                create(
                    "IfcEdge",
                    vertex(-overhang, y, -drop),
                    vertex(SBB_L + overhang, y, -drop),
                ),
            ),
            "RIGID_JOINED_MEMBER",
            up,
        )
        beams.append(beam)
        for x in (-overhang, SBB_L + overhang):
            support = create(
                "IfcStructuralPointConnection",
                guid(),
                None,
                "Support",
                None,
                None,
                placement,
                shape("Vertex", vertex(x, y, -drop)),
                create(
                    "IfcBoundaryNodeCondition",
                    None,
                    *[create("IfcBoolean", True) for _ in range(6)],
                ),
                None,
            )
            connect(beam, support)
            products.append(support)
        line = create(
            "IfcStructuralCurveConnection",
            guid(),
            None,
            "Joint",
            None,
            None,
            placement,
            shape("Edge", create("IfcEdge", vertex(0, y), vertex(SBB_L, y))),
            None,
            up,
        )
        connect(beam, line)
        held, free = create("IfcBoolean", True), create("IfcBoolean", False)
        connect(
            slab,
            line,
            (
                create(
                    "IfcBoundaryEdgeCondition", None, held, held, held, free, free, free
                )
                if released
                else None
            ),
        )
        products += [beam, line]
    create("IfcRelAssociatesMaterial", guid(), None, None, None, beams, profile_set)
    create("IfcRelAssignsToGroup", guid(), None, None, None, products, None, analysis)
    _add_area_load(model, slab, (0.0, 0.0, -SBB_Q))
    path = str(tmp_path / "slab_between_beams.ifc")
    model.write(path)
    return path


def _sag_across(data_dir) -> float:
    """How far the middle of the slab sags below its edges.

    Read from the solver's nodes on the slab's faces, in the middle half of
    its length: it bends as a strip, the same at every x. The slab node
    nearest its centre line is within a few centimetres of it, where the
    deflection is flat to a part in a thousand.
    """
    parser = ResultsParser()
    frd = os.path.join(str(data_dir), "analysis.frd")
    coordinates = parser.parse_node_coordinates(frd)
    vertical = {
        int(result.reference_element): result.get_translations()[2]
        for result in parser.parse_displacements(frd)
    }
    faces = {
        node: xyz
        for node, xyz in coordinates.items()
        if node in vertical
        and abs(abs(xyz[2]) - SBB_T / 2) < 1e-6
        and abs(xyz[0] - SBB_L / 2) < SBB_L / 4
    }

    def uz(y):
        # The faces above and below a point of the middle surface: their
        # mean is its deflection
        nearest = min(faces, key=lambda node: abs(faces[node][1] - y))
        assert abs(faces[nearest][1] - y) < 0.06
        values = [
            vertical[node]
            for node, xyz in faces.items()
            if math.dist(xyz[:2], faces[nearest][:2]) < 1e-6
        ]
        assert len(values) == 2
        return sum(values) / 2

    return uz(0.0) - uz(SBB_B / 2)


class TestSlabJoinedToBeamsAlongALine:
    """A slab joined to its beams by line connections of the file (aiz.51).

    The beams are much stiffer than the slab, so it spans between them as a
    strip with edges that do not move: clamped if the joints are rigid,
    hinged if they release rotation about the line. Mindlin plate theory,
    nu = 0, adds its shear: q B^2 / 8 kappa G t.
    """

    MESH = 0.25

    def _expected(self, clamped: bool) -> float:
        stiffness = SBB_E * SBB_T**3 / 12
        shear = 5.0 / 6.0 * SBB_E / 2 * SBB_T
        bending = SBB_Q * SBB_B**4 / (384 * stiffness)
        return (bending if clamped else 5 * bending) + SBB_Q * SBB_B**2 / (8 * shear)

    def test_rigid_joint_clamps_the_slab(self, tmp_path):
        path = _slab_between_beams(tmp_path)
        _run(path, tmp_path, mesh_size=self.MESH)
        sag = _sag_across(tmp_path / f"out_{self.MESH}")
        assert sag == pytest.approx(self._expected(clamped=True), rel=0.01)

    def test_released_joint_hinges_the_slab(self, tmp_path):
        """Once the slab hung from a point in the middle of each line."""
        path = _slab_between_beams(tmp_path, released=True)
        _run(path, tmp_path, mesh_size=self.MESH)
        sag = _sag_across(tmp_path / f"out_{self.MESH}")
        assert sag == pytest.approx(self._expected(clamped=False), rel=0.01)

    def test_supports_at_its_corners_hold_the_beams_only(self, tmp_path):
        """A support of a beam at a corner of the slab once clamped the slab's
        own node there too, and the hinged slab came out 15% stiff (aiz.97)."""
        path = _slab_between_beams(tmp_path, released=True, overhang=0.0)
        _run(path, tmp_path, mesh_size=self.MESH)
        sag = _sag_across(tmp_path / f"out_{self.MESH}")
        assert sag == pytest.approx(self._expected(clamped=False), rel=0.01)

    def test_downstand_beams_clamp_it_through_links(self, tmp_path):
        path = _slab_between_beams(tmp_path, drop=0.4)
        _run(path, tmp_path, mesh_size=self.MESH)
        sag = _sag_across(tmp_path / f"out_{self.MESH}")
        assert sag == pytest.approx(self._expected(clamped=True), rel=0.01)

    def test_downstand_beams_hinged_to_it(self, tmp_path):
        path = _slab_between_beams(tmp_path, released=True, drop=0.4)
        _run(path, tmp_path, mesh_size=self.MESH)
        sag = _sag_across(tmp_path / f"out_{self.MESH}")
        assert sag == pytest.approx(self._expected(clamped=False), rel=0.01)

    def test_a_line_cannot_join_two_beams(self, tmp_path):
        model = ifcopenshell.open(_slab_between_beams(tmp_path))
        lines = model.by_type("IfcStructuralCurveConnection")
        beams = model.by_type("IfcStructuralCurveMember")
        model.create_entity(
            "IfcRelConnectsStructuralMember",
            ifcopenshell.guid.new(),
            RelatingStructuralMember=beams[1],
            RelatedStructuralConnection=lines[0],
        )
        path = str(tmp_path / "two_beams.ifc")
        model.write(path)
        result = analyze_ifc(ifc_path=path, output_dir=str(tmp_path / "out"))
        assert result["status"] == "failed"
        assert any("joins curve members" in e for e in map(str, result["errors"]))

    def test_supports_carry_the_load(self, tmp_path):
        data = _run(_slab_between_beams(tmp_path), tmp_path, mesh_size=self.MESH)
        total = data["global_reactions"]["by_load_case"]["Imposed"]
        # CalculiX 2.21 is 1.2e-6 short at these clamped ends
        assert total["fz_N"] == pytest.approx(SBB_Q * SBB_L * SBB_B, rel=1e-5)
        beams = [m for m in data["members"] if m["type"] == "curve"]
        assert len(beams) == 2
        (slab,) = [m for m in data["members"] if m["type"] == "surface"]
        for beam in beams:
            assert beam["tied_to_surface_members"] == [slab["id"]]


def _settled_beam(tmp_path, with_other_case: bool = False) -> str:
    """Two 4 m spans over three pinned supports, the middle one settling.

    Case ``Load`` moves the middle support down by ``SETTLEMENT``. With
    ``with_other_case``, case ``Other`` has ``POINT_LOAD`` in the middle of
    the first span and combination ``Both`` is 1.5 ``Load`` + ``Other``.
    """
    path = plane_model(
        str(tmp_path / "settled.ifc"),
        nodes={"A": (0, 0), "M": (2, 0), "B": (4, 0), "C": (8, 0)},
        members=[("A", "M"), ("M", "B"), ("B", "C")],
        supports={"A": PLANE_PIN, "B": PLANE_ROLLER, "C": PLANE_ROLLER},
        loads={"M": (0.0, -TestSupportDisplacements.POINT_LOAD)},
        hinged=False,
        support_displacements={
            "B": (0.0, 0.0, -TestSupportDisplacements.SETTLEMENT, 0.0, 0.0, 0.0)
        },
    )
    model = ifcopenshell.open(path)
    (case,) = model.by_type("IfcStructuralLoadCase")
    (assignment,) = [
        r for r in model.by_type("IfcRelAssignsToGroup") if r.RelatingGroup == case
    ]
    (force,) = [a for a in assignment.RelatedObjects if a.Name == "PM"]
    assignment.RelatedObjects = [a for a in assignment.RelatedObjects if a != force]
    if with_other_case:
        other = model.create_entity(
            "IfcStructuralLoadCase",
            ifcopenshell.guid.new(),
            Name="Other",
            PredefinedType="LOAD_CASE",
            ActionType="NOTDEFINED",
            ActionSource="NOTDEFINED",
        )
        model.create_entity(
            "IfcRelAssignsToGroup",
            ifcopenshell.guid.new(),
            RelatedObjects=[force],
            RelatingGroup=other,
        )
        both = model.create_entity(
            "IfcStructuralLoadGroup",
            ifcopenshell.guid.new(),
            Name="Both",
            PredefinedType="LOAD_COMBINATION",
            ActionType="NOTDEFINED",
            ActionSource="NOTDEFINED",
        )
        for group, factor in ((case, 1.5), (other, 1.0)):
            model.create_entity(
                "IfcRelAssignsToGroupByFactor",
                ifcopenshell.guid.new(),
                RelatedObjects=[group],
                RelatingGroup=both,
                Factor=factor,
            )
    else:
        model.remove(force)
    model.write(path)
    return path


class TestSupportDisplacements:
    """Supports moved by the file (``aiz.58``): settlement and a turned end.

    A prescribed displacement (``IfcStructuralLoadSingleDisplacement``) used
    to stop the analysis. The beam is the 0.1 m square bar of
    ``plane_model``, and the closed forms are Timoshenko's: its shear
    deformation takes 0.05 to 0.3 % off what bending alone gives.
    """

    SETTLEMENT = 0.01
    POINT_LOAD = 10000.0
    SPAN = 4.0
    EI = PLANE_E * 0.1**4 / 12
    # Shear stiffness of the square bar, nu = 0.3, and its ratio to bending
    # over a span
    KGA = 5 / 6 * PLANE_E / 2.6 * 0.1**2
    PHI = 12 * EI / (KGA * SPAN**2)

    def _settling_force(self) -> float:
        """The force that sags a 2 L span by d at midspan: 6 EI d / L^3,
        less what shear adds to the sag."""
        return self.SETTLEMENT / (
            self.SPAN**3 / (6 * self.EI) + self.SPAN / (2 * self.KGA)
        )

    def test_settled_support_is_pulled_down(self, tmp_path):
        data = _run(_settled_beam(tmp_path), tmp_path, mesh_size=0.25)
        force = self._settling_force()
        for x, share in ((0.0, 0.5), (4.0, -1.0), (8.0, 0.5)):
            reaction = _support_at(data, (x, 0.0, 0.0))["by_load_case"]["Load"]
            assert reaction["fz_N"] == pytest.approx(share * force, rel=0.001)
        assert data["global_displacements"]["envelope"]["max_tz_m"] == pytest.approx(
            self.SETTLEMENT, rel=1e-6
        )
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["applied_load_N"] == [0.0, 0.0, 0.0]
        assert total["imbalance_N"] < 1e-6 * force

    def test_other_cases_do_not_move_it(self, tmp_path):
        """A ``*BOUNDARY`` value stays in force until it is written again.

        With the point load alone the middle support takes 11 P / 16; the
        combination is the sum of its cases.
        """
        data = _run(_settled_beam(tmp_path, True), tmp_path, mesh_size=0.25)
        middle = _support_at(data, (4.0, 0.0, 0.0))
        settled = middle["by_load_case"]["Load"]["fz_N"]
        loaded = middle["by_load_case"]["Other"]["fz_N"]
        assert settled == pytest.approx(-self._settling_force(), rel=0.001)
        assert loaded == pytest.approx(11 * self.POINT_LOAD / 16, rel=0.003)
        assert middle["by_load_combination"]["Both"]["fz_N"] == pytest.approx(
            1.5 * settled + loaded, rel=1e-6
        )
        moved = middle["prescribed_displacements"]
        assert moved["by_load_case"] == {
            "Load": {
                "translation_m": [0.0, 0.0, -self.SETTLEMENT],
                "rotation_rad": [0.0, 0.0, 0.0],
            }
        }
        assert moved["by_load_combination"]["Both"]["translation_m"] == (
            pytest.approx([0.0, 0.0, -1.5 * self.SETTLEMENT])
        )
        for x in (0.0, 8.0):
            assert "prescribed_displacements" not in _support_at(data, (x, 0.0, 0.0))

    def test_turned_end_of_a_fixed_beam(self, tmp_path):
        """4 EI t / L at the turned end, 2 EI t / L at the other, 6 EI t / L^2
        of shear, each with Timoshenko's factor."""
        turn = 0.001
        path = plane_model(
            str(tmp_path / "turned.ifc"),
            nodes={"A": (0, 0), "B": (4, 0)},
            members=[("A", "B")],
            supports={"A": PLANE_FIXED, "B": PLANE_FIXED},
            loads={},
            hinged=False,
            support_displacements={"A": (0.0, 0.0, 0.0, 0.0, turn, 0.0)},
        )
        data = _run(path, tmp_path, mesh_size=0.25)
        diagram = _curve_member_diagram(data)
        phi = self.PHI
        near = (4 + phi) / (1 + phi) * self.EI * turn / self.SPAN
        far = (2 - phi) / (1 + phi) * self.EI * turn / self.SPAN
        shear = 6 / (1 + phi) * self.EI * turn / self.SPAN**2
        assert abs(diagram["Mf2_Nm"][0]) == pytest.approx(near, rel=0.001)
        assert abs(diagram["Mf2_Nm"][-1]) == pytest.approx(far, rel=0.001)
        assert diagram["Mf2_Nm"][0] * diagram["Mf2_Nm"][-1] < 0
        assert abs(diagram["Vf2_N"][0]) == pytest.approx(shear, rel=0.001)
        for x, moment in ((0.0, near), (4.0, far)):
            support = _support_at(data, (x, 0.0, 0.0))
            assert support["moments"] in MOMENT_SOURCES
            reaction = support["by_load_case"]["Load"]
            assert reaction["my_Nm"] == pytest.approx(moment, rel=0.01)
            assert abs(reaction["fz_N"]) == pytest.approx(shear, rel=0.01)

    def test_along_a_direction_the_support_leaves_free_is_an_error(self, tmp_path):
        """Moving a roller along its free direction would add a restraint."""
        path = plane_model(
            str(tmp_path / "free.ifc"),
            nodes={"A": (0, 0), "B": (4, 0)},
            members=[("A", "B")],
            supports={"A": PLANE_PIN, "B": PLANE_ROLLER},
            loads={},
            hinged=False,
            support_displacements={"B": (0.01, 0.0, 0.0, 0.0, 0.0, 0.0)},
        )
        result = analyze_ifc(
            ifc_path=path, output_dir=str(tmp_path / "out"), mesh_size=0.5
        )
        assert result["status"] == "failed"
        (error,) = result["errors"]
        assert error["code"] == "E-LOD-007"
        assert "leaves it free" in error["message"]

    def test_buckling_is_an_error(self, tmp_path):
        result = analyze_ifc(
            ifc_path=_settled_beam(tmp_path),
            output_dir=str(tmp_path / "out"),
            mesh_size=0.5,
            analysis_type="linear_buckling",
        )
        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == "E-LOD-007"


def _heated_slab(tmp_path, change, expansion=1.2e-5) -> str:
    """slab_01 on three of its corners, free to curve, heated.

    The line connections of the file hold nothing; point supports at (0, 0)
    (x, y and z), (5, 0) (y and z) and (0, 3) (z) hold it, statically
    determinate. ``change`` is ``(DeltaTConstant, DeltaTZ)`` on a planar
    action, in a load case of its own.
    """
    model = ifcopenshell.open(SLAB)
    slab = model.by_type("IfcStructuralSurfaceMember")[0]
    for relation in model.by_type("IfcRelConnectsStructuralMember"):
        relation.AppliedCondition = None
    for connection in model.by_type("IfcStructuralCurveConnection"):
        connection.AppliedCondition = None
    mechanical = [
        p
        for p in model.by_type("IfcMaterialProperties")
        if p.Name == "Pset_MaterialMechanical"
    ][0]
    mechanical.Properties = list(mechanical.Properties) + [
        model.create_entity(
            "IfcPropertySingleValue",
            "ThermalExpansionCoefficient",
            None,
            model.create_entity("IfcThermalExpansionCoefficientMeasure", expansion),
            None,
        )
    ]
    context = slab.Representation.Representations[0].ContextOfItems
    group = model.by_type("IfcRelAssignsToGroup")[0]
    for corner, held in (
        ((0.0, 0.0, 0.0), (True, True, True)),
        ((SLAB_L, 0.0, 0.0), (False, True, True)),
        ((0.0, SLAB_W, 0.0), (False, False, True)),
    ):
        vertex = model.create_entity(
            "IfcVertexPoint", model.create_entity("IfcCartesianPoint", corner)
        )
        connection = model.create_entity(
            "IfcStructuralPointConnection",
            ifcopenshell.guid.new(),
            slab.OwnerHistory,
            "corner",
            None,
            None,
            slab.ObjectPlacement,
            model.create_entity(
                "IfcProductDefinitionShape",
                None,
                None,
                [
                    model.create_entity(
                        "IfcTopologyRepresentation",
                        context,
                        "Reference",
                        "Vertex",
                        [vertex],
                    )
                ],
            ),
            model.create_entity(
                "IfcBoundaryNodeCondition",
                None,
                *[model.create_entity("IfcBoolean", h) for h in held],
                *[model.create_entity("IfcBoolean", False)] * 3,
            ),
            None,
        )
        model.create_entity(
            "IfcRelConnectsStructuralMember",
            ifcopenshell.guid.new(),
            slab.OwnerHistory,
            None,
            None,
            slab,
            connection,
        )
        group.RelatedObjects = list(group.RelatedObjects) + [connection]
    for case in model.by_type("IfcStructuralLoadCase"):
        for relation in case.IsGroupedBy:
            model.remove(relation)
    action = model.create_entity(
        "IfcStructuralPlanarAction",
        GlobalId=ifcopenshell.guid.new(),
        Name="heat",
        AppliedLoad=model.create_entity(
            "IfcStructuralLoadTemperature",
            None,
            float(change[0]),
            0.0,
            float(change[1]),
        ),
        GlobalOrLocal="LOCAL_COORDS",
        PredefinedType="CONST",
    )
    model.create_entity(
        "IfcRelConnectsStructuralActivity",
        ifcopenshell.guid.new(),
        None,
        None,
        None,
        slab,
        action,
    )
    case = model.create_entity(
        "IfcStructuralLoadCase",
        GlobalId=ifcopenshell.guid.new(),
        Name="Heat",
        PredefinedType="LOAD_CASE",
        ActionType="VARIABLE_Q",
        ActionSource="NOTDEFINED",
    )
    model.create_entity(
        "IfcRelAssignsToGroup",
        ifcopenshell.guid.new(),
        None,
        None,
        None,
        [action],
        None,
        case,
    )
    model.by_type("IfcStructuralAnalysisModel")[0].LoadedBy = [case]
    path = str(tmp_path / "heated_slab.ifc")
    model.write(path)
    return path


class TestTemperatureLoads:
    """Temperature changes of members (``aiz.98``), against closed forms.

    ``IfcStructuralLoadTemperature``: a uniform change, and differences
    between the outer fibres on either side of a member's local y and z
    (across a slab's thickness, z). A curvature of alpha dT / h, where h is
    the real section's depth along that axis. The bar is ``plane_model``'s,
    0.1 m wide (local y, along global Z) and here 0.2 m deep (local z, along
    global Y).
    """

    ALPHA = 1.2e-5
    SPAN = 4.0
    WIDTH = 0.1
    DEPTH = 0.2

    def _bar(self, tmp_path, supports, change, depth=DEPTH, **kwargs) -> str:
        return plane_model(
            str(tmp_path / "bar.ifc"),
            nodes={"A": (0, 0), "B": (self.SPAN, 0)},
            members=[("A", "B")],
            supports=supports,
            loads={},
            hinged=False,
            temperatures={("A", "B"): change},
            expansion=self.ALPHA,
            depth=depth,
            **kwargs,
        )

    def test_free_bar_expands(self, tmp_path):
        data = _run(
            self._bar(tmp_path, {"A": PLANE_FIXED}, (30.0, 0.0, 0.0)),
            tmp_path,
            mesh_size=0.25,
        )
        envelope = data["global_displacements"]["envelope"]
        assert envelope["max_tx_m"] == pytest.approx(self.ALPHA * 30 * self.SPAN)
        assert envelope["max_tz_m"] < 1e-9
        diagram = _curve_member_diagram(data)
        assert max(abs(n) for n in diagram["N_N"]) < 1.0
        # Nothing holds the section's own expansion, and nothing is stressed
        (member,) = [m for m in data["members"] if m["type"] == "curve"]
        assert member["by_load_case"]["Load"]["max_von_mises_Pa"] < 1e3

    def test_clamped_bar_is_compressed(self, tmp_path):
        """N = -E A alpha dT, and the supports push back with it: the one at
        x = 0 towards +x."""
        data = _run(
            self._bar(tmp_path, {"A": PLANE_FIXED, "B": PLANE_FIXED}, (30.0, 0.0, 0.0)),
            tmp_path,
            mesh_size=0.25,
        )
        force = PLANE_E * self.WIDTH * self.DEPTH * self.ALPHA * 30
        diagram = _curve_member_diagram(data)
        for n in diagram["N_N"]:
            assert n == pytest.approx(-force, rel=1e-4)
        assert _support_at(data, (0, 0, 0))["by_load_case"]["Load"][
            "fx_N"
        ] == pytest.approx(force, rel=1e-4)
        total = data["global_reactions"]["by_load_case"]["Load"]
        assert total["applied_load_N"] == [0.0, 0.0, 0.0]
        assert total["imbalance_N"] < 1e-6 * force

    @pytest.mark.parametrize(
        "change, axis, sign, depth",
        [
            # Hotter on local +y, global -Z: it bends up, over the width
            ((0.0, 20.0, 0.0), 2, 1.0, WIDTH),
            # Hotter on local +z, global +Y: it bends to -Y, over the depth
            ((0.0, 0.0, 20.0), 1, -1.0, DEPTH),
        ],
    )
    def test_cantilever_bends_away_from_its_hot_side(
        self, tmp_path, change, axis, sign, depth
    ):
        """Tip alpha dT L^2 / 2 h, with h the section's size across."""
        data = _run(
            self._bar(tmp_path, {"A": PLANE_FIXED}, change), tmp_path, mesh_size=0.25
        )
        expected = self.ALPHA * 20 * self.SPAN**2 / (2 * depth)
        frd = str(tmp_path / "out_0.25" / "analysis.frd")
        displacements = [
            result.get_translations()[axis]
            for result in ResultsParser().parse_displacements(frd)
        ]
        tip = max(displacements, key=abs)
        assert tip == pytest.approx(sign * expected, rel=1e-3)
        diagram = _curve_member_diagram(data)
        for key in ("Mf1_Nm", "Mf2_Nm"):
            assert max(abs(m) for m in diagram[key]) < 1.0

    def test_fixed_beam_under_a_gradient(self, tmp_path):
        """M = E I alpha dT / h all along, and no deflection."""
        data = _run(
            self._bar(
                tmp_path,
                {"A": PLANE_FIXED, "B": PLANE_FIXED},
                (0.0, 20.0, 0.0),
                depth=None,
            ),
            tmp_path,
            mesh_size=0.25,
        )
        moment = PLANE_E * self.WIDTH**4 / 12 * self.ALPHA * 20 / self.WIDTH
        diagram = _curve_member_diagram(data)
        bending = max(
            ("Mf1_Nm", "Mf2_Nm"), key=lambda key: max(abs(m) for m in diagram[key])
        )
        for m in diagram[bending]:
            assert abs(m) == pytest.approx(moment, rel=1e-3)
        for x in (0.0, self.SPAN):
            reaction = _support_at(data, (x, 0.0, 0.0))["by_load_case"]["Load"]
            assert abs(reaction["my_Nm"]) == pytest.approx(moment, rel=1e-3)
        assert data["global_displacements"]["envelope"]["max_tz_m"] < 1e-8

    def test_gradient_across_the_plane_is_not_held_in_it(self, tmp_path):
        """A simply supported beam bowing out of its plane: alpha dT L^2 / 8 h.

        A frame in one plane, loaded in it, is held in it; a temperature
        difference across that plane bends it out, and is not to be held.
        """
        data = _run(
            self._bar(tmp_path, {"A": PLANE_PIN, "B": PLANE_ROLLER}, (0.0, 0.0, 20.0)),
            tmp_path,
            mesh_size=0.25,
        )
        expected = self.ALPHA * 20 * self.SPAN**2 / (8 * self.DEPTH)
        assert data["global_displacements"]["envelope"]["max_ty_m"] == (
            pytest.approx(expected, rel=2e-3)
        )

    def _slab_displacements(self, tmp_path, change):
        """Displacement of each node of the heated slab, by its position."""
        _run(_heated_slab(tmp_path, change), tmp_path, mesh_size=0.5)
        frd = str(tmp_path / "out_0.5" / "analysis.frd")
        parser = ResultsParser()
        coordinates = parser.parse_node_coordinates(frd)
        return [
            (np.array(coordinates[node]), np.array(result.get_translations()))
            for result in parser.parse_displacements(frd)
            for node in [int(result.reference_element)]
            if node in coordinates
        ]

    def test_slab_curves_into_a_sphere(self, tmp_path):
        """Hotter on top, a free slab curves as alpha dT / t both ways.

        On three corners its middle rises by 4.25 m^2 times the curvature,
        and the fourth corner stays level: -k (x^2 + y^2) / 2 + 2.5 k x +
        1.5 k y. Nothing holds it, and nothing is stressed.
        """
        curvature = self.ALPHA * 20 / SLAB_T
        for point, moved in self._slab_displacements(tmp_path, (0.0, 20.0)):
            if abs(point[2]) > 1e-9:
                # A face of the expanded shell, turned with the slab
                continue
            x, y = point[0], point[1]
            expected = curvature * (-(x**2 + y**2) / 2 + 2.5 * x + 1.5 * y)
            assert moved[2] == pytest.approx(expected, abs=0.002 * 4.25 * curvature)

    def test_slab_expands_in_its_plane(self, tmp_path):
        for point, moved in self._slab_displacements(tmp_path, (30.0, 0.0)):
            if abs(point[2]) > 1e-9:
                # The faces of the expanded shell move as it thickens
                continue
            np.testing.assert_allclose(
                moved,
                [self.ALPHA * 30 * point[0], self.ALPHA * 30 * point[1], 0.0],
                atol=1e-3 * self.ALPHA * 30 * SLAB_L,
            )

    def test_other_cases_are_not_heated(self, tmp_path):
        """A temperature stays in force until it is written again."""
        path = self._bar(
            tmp_path,
            {"A": PLANE_FIXED, "B": PLANE_FIXED},
            (30.0, 0.0, 0.0),
            line_loads={("A", "B"): {"values": [(0.0, -1000.0)]}},
            cases={"Other": ["QAB"]},
        )
        data = _run(path, tmp_path, mesh_size=0.25)
        (member,) = [m for m in data["members"] if m["type"] == "curve"]
        diagrams = member["section_force_diagrams"]
        force = PLANE_E * self.WIDTH * self.DEPTH * self.ALPHA * 30
        assert diagrams["Load"]["N_N"][0] == pytest.approx(-force, rel=1e-4)
        assert max(abs(n) for n in diagrams["Other"]["N_N"]) < 1e-3 * force

    def test_node_shared_with_an_unheated_member(self, tmp_path):
        """Between clamps, a heated half and a cold half: N = -E A alpha dT / 2.

        Their shared node takes the mean, which keeps the whole expansion.
        """
        path = plane_model(
            str(tmp_path / "halves.ifc"),
            nodes={"A": (0, 0), "B": (2, 0), "C": (4, 0)},
            members=[("A", "B"), ("B", "C")],
            supports={"A": PLANE_FIXED, "C": PLANE_FIXED},
            loads={},
            hinged=False,
            temperatures={("A", "B"): (30.0, 0.0, 0.0)},
            expansion=self.ALPHA,
            depth=self.DEPTH,
        )
        result = analyze_ifc(
            ifc_path=path, output_dir=str(tmp_path / "out"), mesh_size=0.25
        )
        assert result["status"] == "success", result.get("errors")
        assert "W-LOD-010" in [w["code"] for w in result["warnings"]]
        with open(tmp_path / "out" / "results.json") as fh:
            data = json.load(fh)
        force = PLANE_E * self.WIDTH * self.DEPTH * self.ALPHA * 30 / 2
        for x in (0.0, 4.0):
            reaction = _support_at(data, (x, 0.0, 0.0))["by_load_case"]["Load"]
            assert abs(reaction["fx_N"]) == pytest.approx(force, rel=1e-4)

    def test_without_an_expansion_coefficient_is_an_error(self, tmp_path):
        path = plane_model(
            str(tmp_path / "cold.ifc"),
            nodes={"A": (0, 0), "B": (4, 0)},
            members=[("A", "B")],
            supports={"A": PLANE_FIXED},
            loads={},
            hinged=False,
            temperatures={("A", "B"): (30.0, 0.0, 0.0)},
        )
        result = analyze_ifc(
            ifc_path=path, output_dir=str(tmp_path / "out"), mesh_size=0.5
        )
        assert result["status"] == "failed"
        (error,) = result["errors"]
        assert error["code"] == "E-LOD-008"
        assert "ThermalExpansionCoefficient" in error["message"]

    def test_buckling_is_an_error(self, tmp_path):
        result = analyze_ifc(
            ifc_path=self._bar(tmp_path, {"A": PLANE_FIXED}, (30.0, 0.0, 0.0)),
            output_dir=str(tmp_path / "out"),
            mesh_size=0.5,
            analysis_type="linear_buckling",
        )
        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == "E-LOD-008"


def _frequency_pair_root(bending, shear, mass, rotary, k) -> float:
    """The lower frequency (Hz) of a Timoshenko beam or Mindlin plate wave.

    Per unit length (or width): bending stiffness, shear stiffness, mass and
    rotary inertia; the deflection is sin(k x). The two equations of motion
    give a quadratic in omega squared, whose lower root is the bending mode.
    """
    a = mass * rotary
    b = -(mass * (bending * k**2 + shear) + rotary * shear * k**2)
    c = shear * k**2 * (bending * k**2 + shear) - (shear * k) ** 2
    omega2 = (-b - math.sqrt(b * b - 4 * a * c)) / (2 * a)
    return math.sqrt(omega2) / (2 * math.pi)


def _timoshenko_cantilever_frequencies(
    E, G, kappa, rho, area, inertia, length, count, elements=400
):
    """Bending frequencies (Hz) of a clamped-free Timoshenko beam.

    Finite elements, since the cantilever has no closed form: two nodes,
    linear shape functions, one-point shear integration and a consistent
    mass with rotary inertia. They converge as h^2, to a few parts in a
    million with 400 elements (checked against the closed form of the
    simply supported beam).
    """
    from scipy.linalg import eigh

    h = length / elements
    size = 2 * (elements + 1)
    K = np.zeros((size, size))
    M = np.zeros((size, size))
    bending = np.array([0.0, -1 / h, 0.0, 1 / h])
    shear = np.array([-1 / h, -0.5, 1 / h, -0.5])
    pair = np.array([[2.0, 1.0], [1.0, 2.0]]) * h / 6
    for e in range(elements):
        dofs = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]  # w, theta at each end
        K[np.ix_(dofs, dofs)] += E * inertia * h * np.outer(bending, bending)
        K[np.ix_(dofs, dofs)] += kappa * G * area * h * np.outer(shear, shear)
        M[np.ix_(dofs[0::2], dofs[0::2])] += rho * area * pair
        M[np.ix_(dofs[1::2], dofs[1::2])] += rho * inertia * pair
    free = slice(2, size)
    omega2 = eigh(K[free, free], M[free, free], eigvals_only=True)
    return [math.sqrt(w) / (2 * math.pi) for w in sorted(omega2)[:count]]


def _modes_along(data: dict, direction: str) -> list:
    """Frequencies of the modes that move mass mostly along ``direction``.

    A mode goes with the translation in which its effective mass is largest,
    or with a rotation (``rx``...) when it moves no mass in translation: a
    twist about the member's axis.
    """
    modal = data["modal"]
    totals = modal["total_effective_mass_kg"]
    found = []
    for mode in modal["modes"]:
        masses = mode["effective_mass_kg"]
        along = max(masses, key=masses.get)
        if masses[along] < 1e-6 * totals[along]:
            moments = mode["effective_mass_moment_kgm2"]
            along = max(moments, key=moments.get)
        if along == direction:
            found.append(mode["frequency_Hz"])
    return found


class TestModalAnalysis:
    """Natural frequencies against Timoshenko's beam and Mindlin's plate (lon).

    The mass is the materials' (``Pset_MaterialCommon.MassDensity``), with
    the rotary inertia of the section: an equivalent rectangle has that of
    the real section, rho (Iy + Iz), as well as its mass per length.
    """

    C = TestFixedFixedBeamPointLoad

    def _run(self, path, tmp_path, mesh_size, modes=10, **kwargs) -> dict:
        data = _run(
            path,
            tmp_path,
            mesh_size=mesh_size,
            analysis_type="modal",
            num_modes=modes,
            **kwargs,
        )
        assert data["analysis_type"] == "modal"
        return data

    @staticmethod
    def _closest(frequencies, target) -> float:
        return min(frequencies, key=lambda f: abs(f - target))

    def test_cantilever_bends_as_a_timoshenko_beam(self, tmp_path):
        """cantilever_01 (L/h = 7.5 vertically, 15 sideways), modes 1 to 4.

        The expanded rectangle shears with its whole area and the moduli it
        is given (aiz.101): 5/6 of the material's along its depth, which is
        Timoshenko's beam, and across its width the one set for torsion.
        Against that every mode agrees to 1e-3.
        """
        data = self._run(CANTILEVER, tmp_path, 0.1, modes=12)
        area = 0.2 * 0.4
        vertical_inertia, side_inertia = 0.2 * 0.4**3 / 12, 0.4 * 0.2**3 / 12
        along_depth, across_width = rectangle_shear_moduli(
            0.4,
            0.2,
            CANT_G,
            Section.create_rectangular_section("s", "s", 0.2, 0.4).torsional_constant,
        )
        assert along_depth == pytest.approx(5 / 6 * CANT_G)
        for direction, shear_modulus, inertia in (
            ("z", along_depth, vertical_inertia),
            ("y", across_width, side_inertia),
        ):
            found = _modes_along(data, direction)[:4]
            assert len(found) == 4, (direction, data["modal"]["modes"])
            expected = _timoshenko_cantilever_frequencies(
                CANT_E, shear_modulus, 1.0, CANT_RHO, area, inertia, CANT_L, 4
            )
            assert found == pytest.approx(expected, rel=1e-3), direction
        # Sideways the width modulus is 17 % above 5/6 G; at L/h = 15 that
        # moves the first mode by little
        (truth,) = _timoshenko_cantilever_frequencies(
            CANT_E, CANT_G, 5 / 6, CANT_RHO, area, side_inertia, CANT_L, 1
        )
        assert _modes_along(data, "y")[0] == pytest.approx(truth, rel=1e-3)

    def test_cantilever_stretches_and_twists_as_a_rod(self, tmp_path):
        """Axial modes are exact; torsion is as good as the static benchmark (1 %)."""
        data = self._run(CANTILEVER, tmp_path, 0.1, modes=12)
        (axial,) = _modes_along(data, "x")
        assert axial == pytest.approx(
            math.sqrt(CANT_E / CANT_RHO) / (4 * CANT_L), rel=1e-4
        )
        torsion = Section.create_rectangular_section("s", "s", 0.2, 0.4)
        polar = torsion.moment_of_inertia_y + torsion.moment_of_inertia_z
        speed = math.sqrt(CANT_G * torsion.torsional_constant / (CANT_RHO * polar))
        twisting = _modes_along(data, "rx")[:2]
        assert twisting == pytest.approx(
            [speed / (4 * CANT_L), 3 * speed / (4 * CANT_L)], rel=0.01
        )

    def test_mass_of_the_cantilever(self, tmp_path):
        """The effective masses: of the first mode, and of all the modes."""
        data = self._run(CANTILEVER, tmp_path, 0.1, modes=12)
        mass = CANT_RHO * 0.2 * 0.4 * CANT_L
        modal = data["modal"]
        assert modal["mass_source"] == "materials"
        # Every node but those of the clamped root is free to move
        for direction in "xyz":
            assert modal["total_effective_mass_kg"][direction] == pytest.approx(
                mass, rel=0.01
            )
        # Euler's cantilever puts 61.3 % of its mass in its first mode
        first = next(m for m in modal["modes"] if m["frequency_Hz"] > 0)
        assert first["effective_mass_kg"]["y"] / mass == pytest.approx(0.613, rel=0.01)
        assert modal["mass_fraction"]["y"] > 0.9
        assert modal["modes"][0]["period_s"] == pytest.approx(
            1 / modal["modes"][0]["frequency_Hz"]
        )

    def test_simply_supported_beam(self, tmp_path):
        """beam_01 on a pin and a roller, 4 m of 0.3 m square: modes 1 to 3."""
        pin = (True, True, True, False, False, False)
        roller = (False, True, True, False, False, False)
        data = self._run(_beam_on_supports(tmp_path, pin, roller), tmp_path, 0.1)
        frequencies = [m["frequency_Hz"] for m in data["modal"]["modes"]]
        shear_modulus = self.C.E / (2 * (1 + self.C.NU))
        for n, tolerance in ((1, 0.001), (2, 0.003), (3, 0.006)):
            expected = _frequency_pair_root(
                self.C.E * self.C.INERTIA,
                5 / 6 * shear_modulus * self.C.AREA,
                self.C.DENSITY * self.C.AREA,
                self.C.DENSITY * self.C.INERTIA,
                n * math.pi / self.C.LENGTH,
            )
            assert self._closest(frequencies, expected) == pytest.approx(
                expected, rel=tolerance
            ), n
        # A half sine holds 8 / pi^2 of the mass
        vertical = max(
            data["modal"]["modes"], key=lambda m: m["effective_mass_kg"]["z"]
        )
        mass = self.C.DENSITY * self.C.AREA * self.C.LENGTH
        assert vertical["effective_mass_kg"]["z"] / mass == pytest.approx(
            8 / math.pi**2, rel=0.01
        )
        # Its shape along the beam is that half sine (94g.13.4), to 3e-4 of
        # the peak on the side of the pin. Towards the roller the solver's
        # expanded section sits up to 2e-3 of the peak off it, and at the
        # roller itself 1e-3: under a static load too (7.5e-4 at the roller,
        # where beam theory agrees to 7e-4 on the other side)
        (member,) = data["members"]
        shape = member["mode_shapes"][f"Mode {vertical['mode']}"]
        largest = max(shape["uz_m"], key=abs)
        for distance, value in zip(shape["distance_m"], shape["uz_m"]):
            expected = math.sin(math.pi * distance / self.C.LENGTH)
            near_the_roller = distance > self.C.LENGTH / 2
            assert value / largest == pytest.approx(
                expected, abs=2.5e-3 if near_the_roller else 5e-4
            )

    def test_simply_supported_plate(self, tmp_path):
        """slab_01 held in translation along its four edges: modes (1,1) to (1,2).

        Mindlin's plate with its edges held against twisting is the closed
        form. Held in translation only, the slab is 1.4 % lower at a 0.5 m
        mesh and 1.7 % at 0.25 m, as its static deflection under its weight
        is 2.6 and 3.3 % larger than Navier's (TestSimplySupportedPlateSelfWeight).
        """
        plate = TestSimplySupportedPlateSelfWeight
        path = plate()._plate(tmp_path)
        data = self._run(path, tmp_path, 0.5, modes=6)
        frequencies = [m["frequency_Hz"] for m in data["modal"]["modes"]]
        rigidity = plate.E * plate.T**3 / (12 * (1 - plate.NU**2))
        shear = 5 / 6 * plate.E / (2 * (1 + plate.NU)) * plate.T
        for m, n in ((1, 1), (2, 1), (3, 1), (1, 2)):
            k = math.hypot(m * math.pi / plate.A, n * math.pi / plate.B)
            expected = _frequency_pair_root(
                rigidity, shear, plate.RHO * plate.T, plate.RHO * plate.T**3 / 12, k
            )
            assert self._closest(frequencies, expected) == pytest.approx(
                expected, rel=0.02
            ), (m, n)
        # The first mode over the slab's mesh is sin sin (94g.13.5)
        (slab,) = [m for m in data["members"] if m["type"] == "surface"]
        points = np.array(slab["surface_mesh"]["points_m"])
        lowest = min(data["modal"]["modes"], key=lambda m: m["frequency_Hz"])
        shape = np.array(slab["surface_mode_shapes"][f"Mode {lowest['mode']}"]["uz_m"])
        expected = np.sin(math.pi * points[:, 0] / plate.A) * np.sin(
            math.pi * points[:, 1] / plate.B
        )
        assert np.abs(shape / shape[np.argmax(np.abs(shape))] - expected).max() < 0.02

    def test_i_section_as_its_equivalent_rectangle(self, tmp_path):
        """Shear areas of the web and the flanges, rotary inertia of the real section.

        The equivalent rectangle is calibrated with a shear coefficient of
        1 on the shear area of the real section; its bending modes are
        Timoshenko's with that to 1e-3, about both axes. Its torsion is far
        too stiff: the first torsional mode is 5.4 times Saint-Venant's.
        """
        path = _cantilever_variant(tmp_path, i_profile=True)
        data = self._run(path, tmp_path, 0.1)
        section = Section.create_i_section("s", "s", I_B, I_H, I_TW, I_TF)
        for direction, inertia, shear_area in (
            ("z", I_STRONG, section.shear_area_y),
            ("y", I_WEAK, section.shear_area_z),
        ):
            found = _modes_along(data, direction)[:2]
            expected = _timoshenko_cantilever_frequencies(
                CANT_E,
                CANT_G * shear_area / I_AREA,
                1.0,
                CANT_RHO,
                I_AREA,
                inertia,
                CANT_L,
                len(found),
            )
            assert found and found == pytest.approx(expected, rel=1e-3), direction
        polar = I_STRONG + I_WEAK
        saint_venant = math.sqrt(
            CANT_G * section.torsional_constant / (CANT_RHO * polar)
        ) / (4 * CANT_L)
        assert _modes_along(data, "rx")[0] > 5 * saint_venant

    def test_a_mechanism_is_reported(self, tmp_path):
        """Rollers at both ends: nothing holds the beam along its axis."""
        roller = (False, True, True, False, False, False)
        path = _beam_on_supports(tmp_path, roller, roller)
        result = analyze_ifc(
            path,
            str(tmp_path / "out"),
            analysis_type="modal",
            mesh_size=0.25,
            num_modes=4,
        )
        assert result["status"] == "success", result["errors"]
        with open(tmp_path / "out" / "results.json") as fh:
            modes = json.load(fh)["modal"]["modes"]
        assert modes[0]["mechanism"] and modes[0]["period_s"] is None
        assert modes[0]["effective_mass_kg"]["x"] > 0.9 * (
            self.C.DENSITY * self.C.AREA * self.C.LENGTH
        )
        assert not any(m["mechanism"] for m in modes[1:])
        (warned,) = [w for w in result["warnings"] if w["code"] == "W-CHK-003"]
        assert "1 of the 4 modes" in warned["message"]

    def test_loads_of_the_file_are_not_mass(self, tmp_path):
        """beam_01 as shipped: its load case is left out, and said to be."""
        result = analyze_ifc(
            BEAM, str(tmp_path / "out"), analysis_type="modal", mesh_size=0.5
        )
        assert result["status"] == "success", result["errors"]
        codes = [w["code"] for w in result["warnings"]]
        assert "W-LOD-011" in codes
        assert "W-LOD-001" not in codes
        with open(tmp_path / "out" / "results.json") as fh:
            data = json.load(fh)
        assert data["load_cases"] == []
        assert data["run"]["settings"]["num_modes"] == 10
        assert len(data["modal"]["modes"]) == 10
        frequencies = [m["frequency_Hz"] for m in data["modal"]["modes"]]
        assert frequencies == sorted(frequencies)
        with open(tmp_path / "out" / "analysis.inp") as fh:
            text = fh.read()
        assert "*FREQUENCY" in text and "*CLOAD" not in text and "*DLOAD" not in text

    def test_user_elements_are_refused(self, tmp_path):
        """CalculiX gives U1 elements no mass."""
        path = _cantilever_variant(tmp_path, i_profile=True)
        result = analyze_ifc(
            path,
            str(tmp_path / "out"),
            analysis_type="modal",
            mesh_size=0.5,
            open_sections="user_element",
        )
        assert result["status"] == "failed"
        assert [e["code"] for e in result["errors"]] == ["E-SEC-006"]


def _slab_01_face(model, corners, outer=True):
    """A bound of an IFC face through the corners, as a polygon."""
    loop = model.create_entity(
        "IfcPolyLoop", [model.create_entity("IfcCartesianPoint", c) for c in corners]
    )
    kind = "IfcFaceOuterBound" if outer else "IfcFaceBound"
    return model.create_entity(kind, loop, True)


def _slab_01_piece(model, slab, corners, holes=()):
    """A surface member like slab_01's, with a face of its own."""
    context = slab.Representation.Representations[0].ContextOfItems
    surface = slab.Representation.Representations[0].Items[0].FaceSurface
    bounds = [_slab_01_face(model, corners)]
    bounds += [_slab_01_face(model, hole, outer=False) for hole in holes]
    face = model.create_entity("IfcFaceSurface", bounds, surface, True)
    shape = model.create_entity(
        "IfcProductDefinitionShape",
        None,
        None,
        [
            model.create_entity(
                "IfcTopologyRepresentation", context, "Reference", "Face", [face]
            )
        ],
    )
    piece = model.create_entity(
        "IfcStructuralSurfaceMember",
        ifcopenshell.guid.new(),
        slab.OwnerHistory,
        "piece",
        None,
        None,
        slab.ObjectPlacement,
        shape,
        slab.PredefinedType,
        slab.Thickness,
    )
    for association in slab.HasAssociations:
        association.RelatedObjects = list(association.RelatedObjects) + [piece]
    group = model.by_type("IfcRelAssignsToGroup")[0]
    group.RelatedObjects = list(group.RelatedObjects) + [piece]
    return piece


class TestSlabWithAnOpening:
    """slab_01, 5 by 3 and clamped at both ends, with a 1 m square hole (2uq)."""

    LOOP = ((2.0, 1.0, 0.0), (3.0, 1.0, 0.0), (3.0, 2.0, 0.0), (2.0, 2.0, 0.0))
    AREA = SLAB_L * SLAB_W - 1.0

    def _holed(self, model):
        slab = model.by_type("IfcStructuralSurfaceMember")[0]
        face = slab.Representation.Representations[0].Items[0]
        face.Bounds = [
            model.create_entity(
                "IfcFaceOuterBound", face.Bounds[0].Bound, face.Bounds[0].Orientation
            ),
            _slab_01_face(model, self.LOOP, outer=False),
        ]
        return slab

    def _write(self, model, tmp_path, name) -> str:
        path = str(tmp_path / f"{name}.ifc")
        model.write(path)
        return path

    def test_loads_leave_the_opening_out(self, tmp_path):
        model = ifcopenshell.open(SLAB)
        _add_area_load(model, self._holed(model), (0.0, 0.0, -SLAB_Q))
        data = _run(self._write(model, tmp_path, "holed"), tmp_path, mesh_size=0.5)
        total = data["global_reactions"]["by_load_case"]["Imposed"]
        assert total["fz_N"] == pytest.approx(SLAB_Q * self.AREA, rel=1e-6)

    def test_weight_leaves_the_opening_out(self, tmp_path):
        """Against the same slab with no hole: it weighs less by the hole."""
        solid = _run(SLAB, tmp_path / "solid", mesh_size=0.5, gravity=True)
        model = ifcopenshell.open(SLAB)
        self._holed(model)
        holed = _run(
            self._write(model, tmp_path, "holed"), tmp_path, mesh_size=0.5, gravity=True
        )
        weights = [
            run["global_reactions"]["by_load_case"]["Gravity"]["fz_N"]
            for run in (solid, holed)
        ]
        assert weights[1] / weights[0] == pytest.approx(self.AREA / 15.0, rel=1e-6)

    def test_load_on_a_slab_overlapped_keeps_off_what_fills_the_opening(self, tmp_path):
        """Elements found by outline must not include those in the hole.

        A landing lying on the slab takes elements from it, so its load goes
        by outline; a panel fills the hole, and is inside the outline.
        """
        model = ifcopenshell.open(SLAB)
        slab = self._holed(model)
        landing = ((0.5, 0.5, 0.0), (1.5, 0.5, 0.0), (1.5, 1.5, 0.0), (0.5, 1.5, 0.0))
        _slab_01_piece(model, slab, landing)
        _slab_01_piece(model, slab, self.LOOP)
        analysis_order = model.by_type("IfcRelAssignsToGroup")[0]
        analysis_order.RelatedObjects = list(analysis_order.RelatedObjects)[::-1]
        _add_area_load(model, slab, (0.0, 0.0, -SLAB_Q))
        data = _run(self._write(model, tmp_path, "filled"), tmp_path, mesh_size=0.5)
        total = data["global_reactions"]["by_load_case"]["Imposed"]
        assert total["fz_N"] == pytest.approx(SLAB_Q * self.AREA, rel=1e-6)

    def test_bends_as_the_slab_drawn_in_four_pieces_round_it(self, tmp_path):
        """Nothing closed-form for a plate with a hole, but this is the same plate."""
        model = ifcopenshell.open(SLAB)
        _add_area_load(model, self._holed(model), (0.0, 0.0, -SLAB_Q))
        holed = _run(self._write(model, tmp_path, "holed"), tmp_path, mesh_size=0.25)

        model = ifcopenshell.open(SLAB)
        slab = model.by_type("IfcStructuralSurfaceMember")[0]
        face = slab.Representation.Representations[0].Items[0]
        face.Bounds = [
            _slab_01_face(
                model,
                ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 3.0, 0.0), (0.0, 3.0, 0.0)),
            )
        ]
        right = _slab_01_piece(
            model,
            slab,
            ((3.0, 0.0, 0.0), (5.0, 0.0, 0.0), (5.0, 3.0, 0.0), (3.0, 3.0, 0.0)),
        )
        lower = _slab_01_piece(
            model,
            slab,
            ((2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0), (2.0, 1.0, 0.0)),
        )
        upper = _slab_01_piece(
            model,
            slab,
            ((2.0, 2.0, 0.0), (3.0, 2.0, 0.0), (3.0, 3.0, 0.0), (2.0, 3.0, 0.0)),
        )
        for relation in model.by_type("IfcRelConnectsStructuralMember"):
            edge = relation.RelatedStructuralConnection.Representation
            start = edge.Representations[0].Items[0].EdgeStart.VertexGeometry
            if start.Coordinates[0] > 2.5:
                relation.RelatingStructuralMember = right
        _add_area_load(model, slab, (0.0, 0.0, -SLAB_Q))
        for piece in (right, lower, upper):
            action = model.by_type("IfcStructuralPlanarAction")[0]
            model.create_entity(
                "IfcRelConnectsStructuralActivity",
                ifcopenshell.guid.new(),
                slab.OwnerHistory,
                None,
                None,
                piece,
                model.create_entity(
                    "IfcStructuralPlanarAction",
                    GlobalId=ifcopenshell.guid.new(),
                    OwnerHistory=slab.OwnerHistory,
                    ObjectPlacement=slab.ObjectPlacement,
                    AppliedLoad=action.AppliedLoad,
                    GlobalOrLocal="GLOBAL_COORDS",
                    ProjectedOrTrue="TRUE_LENGTH",
                    PredefinedType="CONST",
                ),
            )
            group = model.by_type("IfcRelAssignsToGroup")
            case = next(
                g for g in group if g.RelatingGroup.is_a("IfcStructuralLoadCase")
            )
            case.RelatedObjects = list(case.RelatedObjects) + [
                model.by_type("IfcStructuralPlanarAction")[-1]
            ]
        pieces = _run(self._write(model, tmp_path, "pieces"), tmp_path / "p", 0.25)

        assert _max_vertical_deflection(holed) == pytest.approx(
            _max_vertical_deflection(pieces), rel=1e-3
        )
        total = pieces["global_reactions"]["by_load_case"]["Imposed"]
        assert total["fz_N"] == pytest.approx(SLAB_Q * self.AREA, rel=1e-6)
