"""Helpers shared by tests that build a domain model by hand."""

import functools
import math
import os
import subprocess
import tempfile

from ifc_structural_mechanics.domain.structural_connection import RigidConnection
from ifc_structural_mechanics.utils.temp_dir import get_temp_dir

RIGID = 1e20


def fixed_support(position, member_id, connection_id="support"):
    """A fully fixed support holding one member.

    A model without a support cannot be analysed, and the writer no longer
    invents one (it used to fix every node at y = 0).
    """
    support = RigidConnection(connection_id, [float(c) for c in position])
    support.set_stiffness_properties(
        {key: RIGID for key in ("dx", "dy", "dz", "drx", "dry", "drz")}
    )
    support.connect_member(member_id)
    return support


def temp_file(suffix="", prefix="tmp", content=None):
    """A new file in the shared temporary directory, with ``content`` if given."""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=get_temp_dir())
    with os.fdopen(fd, "w") as fh:
        if content is not None:
            fh.write(content)
    return path


def check_results_schema(data):
    """Raise if a results dict does not match the JSON Schema of results.json."""
    import jsonschema

    from ifc_structural_mechanics.export import results_schema

    validator = jsonschema.Draft202012Validator(
        results_schema(), format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        raise AssertionError(
            "results.json does not match its schema:\n"
            + "\n".join(
                f"  {'/'.join(map(str, error.path)) or '(top)'}: {error.message}"
                for error in errors[:10]
            )
        )


def _ifcopenshell():
    import ifcopenshell
    import ifcopenshell.guid

    return ifcopenshell


# Support conditions (dx, dy, dz, drx, dry, drz) for structures in the X-Z plane
PLANE_PIN = (True, True, True, False, False, False)
PLANE_ROLLER = (False, True, True, False, False, False)
# As a two-dimensional textbook gives them: nothing across the plane
PLANE_PIN_2D = (True, False, True, False, False, False)
PLANE_ROLLER_2D = (False, False, True, False, False, False)
PLANE_FIXED = (True, True, True, True, True, True)
PLANE_FIXED_2D = (True, False, True, False, True, False)


def plane_model(
    path,
    nodes,
    members,
    supports,
    loads,
    hinged=True,
    e=2.1e11,
    nu=0.3,
    side=0.1,
    density=None,
    release=PLANE_PIN,
    load_y=0.0,
    support_axes=None,
    line_loads=None,
    moments=None,
    local_loads=None,
    support_displacements=None,
    temperatures=None,
    expansion=None,
    depth=None,
    cases=None,
    turn=0.0,
):
    """Write a truss or frame of square bars in the global X-Z plane, in metres.

    Args:
        path: Where to write the IFC4 file.
        nodes: ``{name: (x, z)}``, or ``(x, y, z)`` for a structure that leaves
            the plane; each becomes a point connection.
        members: ``[(name, name)]``, the two joints of each curve member.
        supports: ``{name: (dx, dy, dz, drx, dry, drz)}``, True where held.
        loads: ``{name: (fx, fz)}`` in newtons, in one load case, ``Load``.
        hinged: Whether the members are released at both ends (``release``).
        e, nu: Elastic constants of the material.
        side: Side of the square section.
        density: Mass density; none when left out.
        release: The rotations a hinged member end keeps (True) or is
            released in (False), after three translations, in the member's
            own axes: x along it, z across the plane.
        load_y: A force across the plane added to every load.
        support_axes: ``{name: (z axis, x axis)}``, the axes the condition of
            a support is given in (its ``ConditionCoordinateSystem``); the
            global ones when left out.
        line_loads: ``{(name, name): {...}}``, a load along that member, in
            the same load case. ``values`` are ``[(fx, fz)]`` in N/m: one for a
            constant load (an ``IfcStructuralLinearAction``), more for one
            that varies (an ``IfcStructuralCurveAction`` with a load
            configuration), at ``locations`` along the member from its first
            joint, which may be left out for two values. Further keys:
            ``distribution`` (LINEAR unless given; SINUS or PARABOLA with one
            value, its peak; DISCRETE with ``values`` that are point forces in
            newtons), ``projected`` and ``local`` (per projected length; in
            the member's own axes, the values then being ``(fx, fz)`` there),
            and ``moment``, the ``(mx, my, mz)`` per length of a constant
            load or the moment of every force of a DISCRETE one.
        moments: ``{name: (mx, my, mz)}`` in N·m, applied at that joint with
            its load, or by themselves.
        local_loads: ``{name: None or (name, name)}``, the loads that are in
            LOCAL_COORDS: in the axes of their joint (``support_axes``), or
            in those of that member, to which the action is then assigned.
        support_displacements: ``{name: (dx, dy, dz, rx, ry, rz)}`` in metres
            and radians, a prescribed displacement of that joint (an
            ``IfcStructuralLoadSingleDisplacement``) in the load case.
        temperatures: ``{(name, name): (dT, dTY, dTZ)}`` in K, a temperature
            change of that member (an ``IfcStructuralLoadTemperature`` on a
            curve action) in the load case.
        expansion: The material's thermal expansion coefficient
            (``Pset_MaterialMechanical.ThermalExpansionCoefficient``), 1/K.
        depth: Depth of the section along the member's local z (across the
            plane), when it is not ``side``: a ``side`` by ``depth``
            rectangle.
        cases: ``{name: [actions]}``, further load cases, each with the
            actions named ``P<joint>``, ``Q<joint><joint>``,
            ``D<joint>`` or ``T<joint><joint>`` that it holds; the
            ``Load`` case holds them all unless they are listed here.
        turn: An angle in degrees about global Z by which the placement of
            every item turns the whole structure, its supports' axes and
            its loads with it: a plane off the global axes.

    Returns:
        *path*.
    """
    ifcopenshell = _ifcopenshell()
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
    if turn:
        angle = math.radians(turn)
        placement = create(
            "IfcLocalPlacement",
            None,
            create(
                "IfcAxis2Placement3D",
                create("IfcCartesianPoint", (0.0, 0.0, 0.0)),
                up,
                create("IfcDirection", (math.cos(angle), math.sin(angle), 0.0)),
            ),
        )
    units = create(
        "IfcUnitAssignment", [create("IfcSIUnit", None, "LENGTHUNIT", None, "METRE")]
    )
    context = create(
        "IfcGeometricRepresentationContext", None, "Model", 3, 1e-5, axes, None
    )
    project = create(
        "IfcProject", guid(), None, "Plane", None, None, None, None, [context], units
    )
    analysis = create(
        "IfcStructuralAnalysisModel",
        guid(),
        None,
        "Plane",
        None,
        None,
        "LOADING_3D",
        axes,
        None,
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
                create("IfcModulusOfElasticityMeasure", e),
                None,
            ),
            create(
                "IfcPropertySingleValue",
                "PoissonRatio",
                None,
                create("IfcPositiveRatioMeasure", nu),
                None,
            ),
        ]
        + (
            [
                create(
                    "IfcPropertySingleValue",
                    "ThermalExpansionCoefficient",
                    None,
                    create("IfcThermalExpansionCoefficientMeasure", expansion),
                    None,
                )
            ]
            if expansion is not None
            else []
        ),
        material,
    )
    if density is not None:
        create(
            "IfcMaterialProperties",
            "Pset_MaterialCommon",
            None,
            [
                create(
                    "IfcPropertySingleValue",
                    "MassDensity",
                    None,
                    create("IfcMassDensityMeasure", density),
                    None,
                )
            ],
            material,
        )
    profile = create("IfcRectangleProfileDef", "AREA", "Bar", None, side, depth or side)
    profile_set = create(
        "IfcMaterialProfileSet",
        None,
        None,
        [create("IfcMaterialProfile", "Bar", None, material, profile, None, None)],
        None,
    )

    def vertex(name):
        point = nodes[name]
        x, y, z = point if len(point) == 3 else (point[0], 0.0, point[1])
        return create(
            "IfcVertexPoint",
            create("IfcCartesianPoint", (float(x), float(y), float(z))),
        )

    def shape(kind, item):
        topology = create(
            "IfcTopologyRepresentation", context, "Reference", kind, [item]
        )
        return create("IfcProductDefinitionShape", None, None, [topology])

    def condition(flags):
        return create(
            "IfcBoundaryNodeCondition",
            None,
            *[create("IfcBoolean", bool(f)) for f in flags],
        )

    def condition_axes(name):
        if name not in (support_axes or {}):
            return None
        z_axis, x_axis = support_axes[name]
        return create(
            "IfcAxis2Placement3D",
            create("IfcCartesianPoint", (0.0, 0.0, 0.0)),
            create("IfcDirection", tuple(float(v) for v in z_axis)),
            create("IfcDirection", tuple(float(v) for v in x_axis)),
        )

    products = []
    joints = {}
    for name in nodes:
        flags = supports.get(name)
        joints[name] = create(
            "IfcStructuralPointConnection",
            guid(),
            None,
            name,
            None,
            None,
            placement,
            shape("Vertex", vertex(name)),
            condition(flags) if flags else None,
            condition_axes(name),
        )
        products.append(joints[name])
    bars = []
    bar_of = {}
    for a, b in members:
        bar = create(
            "IfcStructuralCurveMember",
            guid(),
            None,
            f"{a}{b}",
            None,
            None,
            placement,
            shape("Edge", create("IfcEdge", vertex(a), vertex(b))),
            "PIN_JOINED_MEMBER" if hinged else "RIGID_JOINED_MEMBER",
            create("IfcDirection", (0.0, 1.0, 0.0)),
        )
        for end in (a, b):
            create(
                "IfcRelConnectsStructuralMember",
                guid(),
                None,
                None,
                None,
                bar,
                joints[end],
                condition(release) if hinged else None,
                None,
                None,
                None,
            )
        bars.append(bar)
        bar_of[(a, b)] = bar
        products.append(bar)
    create("IfcRelAssociatesMaterial", guid(), None, None, None, bars, profile_set)
    create("IfcRelAssignsToGroup", guid(), None, None, None, products, None, analysis)
    case = create(
        "IfcStructuralLoadCase",
        guid(),
        None,
        "Load",
        None,
        None,
        "LOAD_CASE",
        "NOTDEFINED",
        "NOTDEFINED",
        None,
        None,
        None,
    )
    actions = []
    moments = dict(moments or {})
    local_loads = dict(local_loads or {})
    point_loads = {name: (0.0, 0.0) for name in moments}
    point_loads.update(loads)
    for name, (fx, fz) in point_loads.items():
        applied = name in loads
        action = create(
            "IfcStructuralPointAction",
            guid(),
            None,
            f"P{name}",
            None,
            None,
            placement,
            shape("Vertex", vertex(name)),
            create(
                "IfcStructuralLoadSingleForce",
                None,
                float(fx),
                float(load_y) if applied else 0.0,
                float(fz),
                *[float(m) for m in moments.get(name, (0.0, 0.0, 0.0))],
            ),
            "LOCAL_COORDS" if name in local_loads else "GLOBAL_COORDS",
            None,
        )
        create(
            "IfcRelConnectsStructuralActivity",
            guid(),
            None,
            None,
            None,
            bar_of[local_loads[name]] if local_loads.get(name) else joints[name],
            action,
        )
        actions.append(action)
    for ends, load in (line_loads or {}).items():
        distribution = load.get("distribution")
        forces = [
            create(
                (
                    "IfcStructuralLoadSingleForce"
                    if distribution == "DISCRETE"
                    else "IfcStructuralLoadLinearForce"
                ),
                None,
                float(fx),
                0.0,
                float(fz),
                *[float(m) for m in load.get("moment", (0.0, 0.0, 0.0))],
            )
            for fx, fz in load["values"]
        ]
        varies = len(forces) > 1 or distribution == "DISCRETE"
        locations = load.get("locations")
        action = create(
            (
                "IfcStructuralCurveAction"
                if varies or distribution
                else "IfcStructuralLinearAction"
            ),
            guid(),
            None,
            f"Q{ends[0]}{ends[1]}",
            None,
            None,
            placement if turn else None,
            None,
            (
                create(
                    "IfcStructuralLoadConfiguration",
                    None,
                    forces,
                    [[float(at)] for at in locations] if locations else None,
                )
                if varies
                else forces[0]
            ),
            "LOCAL_COORDS" if load.get("local") else "GLOBAL_COORDS",
            None,
            "PROJECTED_LENGTH" if load.get("projected") else "TRUE_LENGTH",
            distribution or ("LINEAR" if varies else "CONST"),
        )
        create(
            "IfcRelConnectsStructuralActivity",
            guid(),
            None,
            None,
            None,
            bar_of[ends],
            action,
        )
        actions.append(action)
    for name, values in (support_displacements or {}).items():
        action = create(
            "IfcStructuralPointAction",
            guid(),
            None,
            f"D{name}",
            None,
            None,
            None,
            None,
            create(
                "IfcStructuralLoadSingleDisplacement",
                None,
                *[float(v) for v in values],
            ),
            "GLOBAL_COORDS",
            None,
        )
        create(
            "IfcRelConnectsStructuralActivity",
            guid(),
            None,
            None,
            None,
            joints[name],
            action,
        )
        actions.append(action)
    for ends, (constant, across_y, across_z) in (temperatures or {}).items():
        action = create(
            "IfcStructuralCurveAction",
            guid(),
            None,
            f"T{ends[0]}{ends[1]}",
            None,
            None,
            None,
            None,
            create(
                "IfcStructuralLoadTemperature",
                None,
                float(constant),
                float(across_y),
                float(across_z),
            ),
            "LOCAL_COORDS",
            None,
            None,
            "CONST",
        )
        create(
            "IfcRelConnectsStructuralActivity",
            guid(),
            None,
            None,
            None,
            bar_of[ends],
            action,
        )
        actions.append(action)
    listed = {name for names in (cases or {}).values() for name in names}
    create(
        "IfcRelAssignsToGroup",
        guid(),
        None,
        None,
        None,
        [action for action in actions if action.Name not in listed],
        None,
        case,
    )
    loaded_by = [case]
    for name, names in (cases or {}).items():
        other = create(
            "IfcStructuralLoadCase",
            guid(),
            None,
            name,
            None,
            None,
            "LOAD_CASE",
            "NOTDEFINED",
            "NOTDEFINED",
            None,
            None,
            None,
        )
        create(
            "IfcRelAssignsToGroup",
            guid(),
            None,
            None,
            None,
            [action for action in actions if action.Name in names],
            None,
            other,
        )
        loaded_by.append(other)
    analysis.LoadedBy = loaded_by
    model.write(path)
    return path


_CLAMPED_REACTION_INPUT = """*NODE
1,0,0,0
2,0,0,1
3,0,0,2
*ELEMENT, TYPE=B32R, ELSET=B
1,1,2,3
*NSET,NSET=S
1
*MATERIAL,NAME=M
*ELASTIC
2e11,0.3
*BEAM SECTION,ELSET=B,MATERIAL=M,SECTION=RECT
0.2,0.1
1,0,0
*BOUNDARY
1,1,6
*STEP
*STATIC
*CLOAD
3,1,100.
3,3,-1000.
*NODE PRINT,NSET=S,TOTALS=ONLY
RF
*END STEP
"""


@functools.lru_cache(maxsize=None)
def solver_reports_clamped_reactions() -> bool:
    """Whether the installed CalculiX gets the reaction at a clamped end right.

    2.21 does not (1077 N for this 1000 N pull on a clamped bar that is also
    bent); 2.23 does. Tests of the solver's own reactions at such supports
    cannot pass on 2.21, and ``TestSolverReactionsAreChecked`` covers what
    the results say then.
    """
    with tempfile.TemporaryDirectory() as folder:
        with open(os.path.join(folder, "clamped.inp"), "w") as fh:
            fh.write(_CLAMPED_REACTION_INPUT)
        subprocess.run(
            ["ccx", "-i", "clamped"], cwd=folder, capture_output=True, check=False
        )
        with open(os.path.join(folder, "clamped.dat")) as fh:
            lines = [line.split() for line in fh if line.strip()]
    return abs(float(lines[-1][2]) - 1000.0) < 1.0
