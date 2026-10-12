"""Helpers shared by tests that build a domain model by hand."""

from ifc_structural_mechanics.domain.structural_connection import RigidConnection

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
            ``distribution`` (LINEAR unless given), ``projected`` and
            ``local`` (per projected length; in the member's own axes, the
            values then being ``(fx, fz)`` there), and ``moment``, the
            ``(mx, my, mz)`` per length of a constant load.
        moments: ``{name: (mx, my, mz)}`` in N·m, applied at that joint with
            its load, or by themselves.

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
        ],
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
    profile = create("IfcRectangleProfileDef", "AREA", "Bar", None, side, side)
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
    for ends, load in (line_loads or {}).items():
        forces = [
            create(
                "IfcStructuralLoadLinearForce",
                None,
                float(fx),
                0.0,
                float(fz),
                *[float(m) for m in load.get("moment", (0.0, 0.0, 0.0))],
            )
            for fx, fz in load["values"]
        ]
        varies = len(forces) > 1
        locations = load.get("locations")
        action = create(
            "IfcStructuralCurveAction" if varies else "IfcStructuralLinearAction",
            guid(),
            None,
            f"Q{ends[0]}{ends[1]}",
            None,
            None,
            None,
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
            load.get("distribution", "LINEAR") if varies else "CONST",
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
    create("IfcRelAssignsToGroup", guid(), None, None, None, actions, None, case)
    analysis.LoadedBy = [case]
    model.write(path)
    return path
