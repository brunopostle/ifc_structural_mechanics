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
* Simply supported rectangular plate under uniform load: Navier's double
  sine series, plus the Mindlin shear term ``M / (kappa G t)`` where ``M`` is
  the moment sum
"""

import json
import math
import os
import shutil

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc  # noqa: E402

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


def _slab_variant(tmp_path, edge_conditions, extra_edges=()) -> str:
    """Write a copy of slab_01.ifc with new line supports.

    slab_01 is a 5 m x 3 m slab, 0.2 m thick, with line supports along x = 0
    and x = 5. ``edge_conditions`` gives the support condition of those two, in
    that order. ``extra_edges`` adds line supports, each as (start, end, fixed).
    The conditions on the member side of each connection are removed, so the
    support condition alone decides how the edge behaves.
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


def _beam_with_line_load(tmp_path, force_per_metre) -> str:
    """Write beam_01.ifc with its point load replaced by a uniform line load.

    ``force_per_metre`` is the load in global axes, in N/m. beam_01 is in
    millimetres and newtons, so it is written in N/mm.
    """
    model = ifcopenshell.open(BEAM)
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


class TestSimplySupportedPlateSelfWeight:
    """slab_01 supported in translation along all four edges, under gravity.

    This is the check on shell bending. Linear S3 shells gave about half the
    deflection at a 0.5 m mesh and were still 20 % short at 0.25 m.
    """

    A, B, T = 5.0, 3.0, 0.2
    E, NU, RHO = 2.1e8, 0.2, 7.8
    PINNED = (True, True, True, False, False, False)

    def _plate(self, tmp_path) -> str:
        return _slab_variant(
            tmp_path,
            edge_conditions=(self.PINNED, self.PINNED),
            extra_edges=(
                ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0), self.PINNED),
                ((0.0, 3.0, 0.0), (5.0, 3.0, 0.0), self.PINNED),
            ),
        )

    def _centre_deflection(self) -> float:
        """Navier series for the centre, with the Mindlin shear deflection."""
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
