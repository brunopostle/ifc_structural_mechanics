"""The warnings the analysis gives, each with a code that users can look up.

Every warning in ``result["warnings"]`` carries a ``code`` such as
``W-SUP-001``: W for a warning, the stage of the analysis it comes from, and
a number. Within a stage the warnings most likely to be met come first. A code
is never renumbered or given to another warning; one that is no longer used
stays in the list, marked as retired.

``docs/messages.md`` is written from this module
(``python -m ifc_structural_mechanics.utils.messages > docs/messages.md``),
and a test fails when it is out of date.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageKind:
    """One kind of warning: what it says, and what to do about it."""

    code: str
    title: str
    explanation: str


# The stages of the analysis, in the order they run
STAGES = {
    "IFC": "Reading the IFC file",
    "MAT": "Materials",
    "SEC": "Sections",
    "MSH": "Meshing",
    "JNT": "Joints between members",
    "SUP": "Supports",
    "LOD": "Loads, load cases and load combinations",
    "SLV": "The solver",
    "RES": "Reading the results",
    "CHK": "Plausibility of the results",
}

_KINDS = [
    # Reading the IFC file
    MessageKind(
        "W-IFC-001",
        "More than one structural analysis model",
        "The file has several IfcStructuralAnalysisModel and only the first is "
        "analysed. Split the file, or put the model to analyse first.",
    ),
    MessageKind(
        "W-IFC-002",
        "Members without a material",
        "Members of the model have no material. CalculiX cannot analyse them "
        "and the analysis will fail. Assign an IfcMaterial with "
        "Pset_MaterialMechanical to each structural member.",
    ),
    MessageKind(
        "W-IFC-003",
        "Curve members without a section",
        "Curve members of the model have no profile. CalculiX cannot analyse "
        "them and the analysis will fail. Assign an IfcMaterialProfileSet "
        "with a profile to each curve member.",
    ),
    # Materials
    MessageKind(
        "W-MAT-001",
        "Material without a mass density",
        "The material has no Pset_MaterialCommon.MassDensity, so its members "
        "weigh nothing. That is only right if no load case includes "
        "self-weight; when one does, or --gravity is given, the analysis "
        "stops instead. Give the material its density.",
    ),
    MessageKind(
        "W-MAT-002",
        "Material without a Poisson's ratio",
        "The material has neither Pset_MaterialMechanical.PoissonRatio nor a "
        "shear modulus, and 0.3 is used. That suits steel and is near enough "
        "for most concrete (0.2) in bending; shear and torsion stiffness "
        "depend on it. Give the material its ratio.",
    ),
    MessageKind(
        "W-MAT-003",
        "Shear modulus does not agree with the other constants",
        "The material gives Young's modulus, Poisson's ratio and a shear "
        "modulus that an isotropic material cannot have together. The "
        "analysis uses Young's modulus and Poisson's ratio. Check which of "
        "the three is right.",
    ),
    # Sections
    MessageKind(
        "W-SEC-001",
        "Torsion of solid rectangles corrected",
        "CalculiX makes a solid rectangular beam too stiff in torsion (18.5 % "
        "for a square). The shear stiffness across the member's width is "
        "lowered until its torsion is right, which leaves bending and shear "
        "along its depth as they are. Shear across the width is softer than "
        "it should be by the percentage given. Nothing needs doing unless a "
        "result depends on that shear.",
    ),
    MessageKind(
        "W-SEC-002",
        "Sections analysed as equivalent rectangles",
        "CalculiX has no I, T, L or channel shape, so these members are "
        "rectangles with the same area, bending stiffness and weight. Their "
        "deflections and section forces are right; their stress is worked "
        "out from the section forces and the real section "
        "(max_normal_stress_Pa), and the solver's own stresses are not given. "
        "An open section is far too stiff in torsion: do not rely on results "
        "where such members carry torsion. Closed and round sections have "
        "their torsion right and are up to twice too stiff in shear.",
    ),
    MessageKind(
        "W-SEC-003",
        "Section orientation guessed",
        "The members have no usable Axis (IFC2X3 has none; an axis along the "
        "member says nothing), so which way the section faces is a guess: "
        "its depth as near vertical as the member allows, along global X for "
        "a vertical member. Strong and weak axes may be the wrong way round. "
        "Give each curve member an Axis.",
    ),
    MessageKind(
        "W-SEC-004",
        "Section approximated",
        "Something of the member's section could not be represented exactly; "
        "the message says what.",
    ),
    # Meshing
    MessageKind(
        "W-MSH-001",
        "Members overlap",
        "Two members occupy the same place (a short beam inside a longer one, "
        "a landing in a floor slab). The mesh has one set of elements there, "
        "analysed with the material and section or thickness of the member "
        "that comes first in the file, not both. Remove the overlap if both "
        "were meant to carry load.",
    ),
    MessageKind(
        "W-MSH-002",
        "Members with no elements",
        "These members lie wholly inside others (see W-MSH-001) and have no "
        "elements of their own. They take no part in the analysis and have no "
        "results; the member they overlap carries their share.",
    ),
    # Joints between members
    MessageKind(
        "W-JNT-001",
        "Curve members tied to the surface members they lie in",
        "A beam along the edge of a slab, or a column in a wall, with no "
        "connection in the file along their length, is tied to the surface "
        "in translation along it, as a slab bears on its beams. Without this "
        "a slab connected at its corners spans corner to corner. The member's "
        "section forces are its share only; where force passes between the "
        "two at a point they change abruptly and depend on the mesh size. "
        "Use --strict-connections to analyse only the connections in the "
        "file.",
    ),
    MessageKind(
        "W-JNT-002",
        "Curve members touching without a connection",
        "A beam ending on the span of another, or two members crossing, share "
        "one mesh node there, which joins them rigidly, whether or not the "
        "file connects them and with --strict-connections too. Most analysis "
        "programs do the same. Add a connection with a release if the joint "
        "is meant to be a pin.",
    ),
    MessageKind(
        "W-JNT-003",
        "Curve members tied to a surface member at a point",
        "A column ending on a slab or passing through it, with no connection "
        "in the file, is tied to it in translation there. Use "
        "--strict-connections to analyse only the connections in the file.",
    ),
    MessageKind(
        "W-JNT-004",
        "Curve members left unconnected to the surface they lie in",
        "--strict-connections was given, so beams along a slab with no "
        "connection in the file are not tied to it, and a slab connected only "
        "at its corners spans between them. Expect large deflections if that "
        "is not what the file means.",
    ),
    MessageKind(
        "W-JNT-005",
        "Curve members left unconnected to a surface at a point",
        "--strict-connections was given, so columns meeting a slab where the "
        "file has no connection are not joined to it.",
    ),
    MessageKind(
        "W-JNT-006",
        "Member end too far from its connection",
        "The member ends further from the connection than a rigid link can "
        "bridge, so it is tied to the joint in translation only and carries "
        "no moment there. Check the geometry of the member and the position "
        "of the connection.",
    ),
    MessageKind(
        "W-JNT-007",
        "Partial rotational release analysed as a pin",
        "The member is released about some rotations at the connection, "
        "which cannot be represented where it is, and it is released about "
        "all three. The joint is more flexible than the file says.",
    ),
    MessageKind(
        "W-JNT-008",
        "Connection with no nodes",
        "No mesh node of the connected members was found at the connection, "
        "so it joins nothing. Check that the connection lies on its members.",
    ),
    MessageKind(
        "W-JNT-009",
        "Spring connection between members not implemented",
        "A connection between members with spring stiffness is not modelled "
        "and joins nothing. Springs at supports are.",
    ),
    MessageKind(
        "W-JNT-010",
        "Connection of an unknown type",
        "The connection is of a type the writer does not know and joins "
        "nothing. Report it.",
    ),
    # Supports
    MessageKind(
        "W-SUP-001",
        "Members held against spinning about their own axis",
        "Nothing restrains these members' rotation about their own axis: "
        "ball supports at both ends of a beam are the usual cause. Each, or "
        "the straight run of members it is part of, is held in torsion at one "
        "of its supports so that the results are defined. Nothing else "
        "changes. Restrain that rotation at a support to be explicit.",
    ),
    MessageKind(
        "W-SUP-002",
        "Plane structure held in its plane",
        "Every member and load lies in one plane and nothing holds the "
        "structure there, so it is analysed as a plane frame: every node is "
        "held across the plane. Forces and displacements in the plane are "
        "not affected. Add supports across the plane to analyse it in three "
        "dimensions.",
    ),
    MessageKind(
        "W-SUP-003",
        "Possible mechanism",
        "No support restrains a rotation and no joint between members carries "
        "moment, so under sideways load the structure may be a mechanism. "
        "CalculiX may report a zero pivot or very large displacements. Check "
        "the rotations of the supports' IfcBoundaryNodeCondition and the "
        "releases at the joints.",
    ),
    MessageKind(
        "W-SUP-004",
        "Members free to spin that could not be held",
        "As W-SUP-001, but there was no support to hold them at, so their "
        "displacements include an arbitrary rotation about their axis. "
        "Restrain that rotation at a support or joint.",
    ),
    MessageKind(
        "W-SUP-005",
        "Supports that support nothing",
        "These supports are connected to no member and lie on none, so they "
        "are left out. Connect them to the members they hold.",
    ),
    MessageKind(
        "W-SUP-006",
        "Rotational spring about a shell's normal left out",
        "Shell nodes have no rotation about the shell's normal, so a spring "
        "about it holds nothing and is left out.",
    ),
    MessageKind(
        "W-SUP-007",
        "No connections",
        "The model has no structural connections, so nothing supports it and "
        "the analysis will fail. Add supports (connections with an "
        "AppliedCondition).",
    ),
    # Loads
    MessageKind(
        "W-LOD-001",
        "No loads",
        "No load case has loads or self-weight and --gravity was not given, "
        "so the analysis has nothing to analyse. Give --gravity if "
        "self-weight is the load meant.",
    ),
    MessageKind(
        "W-LOD-002",
        "Loads in no load case",
        "These loads belong to no load group or load case, so no step "
        "applies them. Assign them to a load case.",
    ),
    MessageKind(
        "W-LOD-003",
        "Self-weight asked for twice",
        "--gravity was given and load cases of the file already include "
        "self-weight. The weight is analysed again as a load case of its own, "
        "Gravity, which no combination includes. Leave out --gravity to use "
        "the file's load cases alone.",
    ),
    MessageKind(
        "W-LOD-004",
        "Load combinations with no load case",
        "These load combinations include no load case and have no results.",
    ),
    MessageKind(
        "W-LOD-005",
        "Load combinations including something other than a load case",
        "A combination may only include load cases. These include another "
        "group (a load group or another combination) and have no results.",
    ),
    MessageKind(
        "W-LOD-006",
        "Load combinations in a buckling analysis",
        "Combinations are only formed in a linear static analysis, by adding "
        "up the results of their load cases. A buckling analysis has none.",
    ),
    MessageKind(
        "W-LOD-007",
        "Point load moved to the nearest node",
        "The point load is further than 0.1 m from any mesh node and is "
        "applied at the nearest one. Check that it lies on a member.",
    ),
    MessageKind(
        "W-LOD-008",
        "Load in the local axes of an item that has none",
        "The load is given in local coordinates, but the member or connection "
        "it is assigned to has no axes of its own, so it is applied in global "
        "axes. Check its direction.",
    ),
    MessageKind(
        "W-LOD-009",
        "Load on a member with no elements",
        "The member lost its elements to a member it overlaps (W-MSH-002), so "
        "its loads are not applied. Assign them to the member that remains.",
    ),
    # The solver
    MessageKind(
        "W-SLV-001",
        "Warning from CalculiX",
        "CalculiX printed this warning, given once for each kind with a "
        "count. The analysis removes the causes it knows of, so one that "
        "appears is worth reporting with the input file.",
    ),
    MessageKind(
        "W-SLV-002",
        "More warnings from CalculiX",
        "CalculiX printed more kinds of warning than are listed; the rest are "
        "in its output.",
    ),
    # Reading the results
    MessageKind(
        "W-RES-001",
        "Reactions corrected",
        "CalculiX 2.21 and earlier misreport the force at a support that "
        "holds a rotation. Such supports have their forces taken from the "
        "ends of their members (good to about 1 %), and the message says "
        "which totals still do not balance the loads. Displacements and "
        "member forces are not affected. CalculiX 2.23 does not need this.",
    ),
    MessageKind(
        "W-RES-002",
        "Results left out",
        "The solver wrote values that are not numbers or are out of range, "
        "and they are left out. Report it with the input file.",
    ),
    MessageKind(
        "W-RES-003",
        "Forces at supports of U1 elements do not balance",
        "CalculiX gets the forces of its U1 elements wrong, and the analysis "
        "works them out from the elements' stiffness instead. Here neither "
        "set balances the loads: this version of CalculiX may have a "
        "different U1 element. Do not rely on the reactions.",
    ),
    MessageKind(
        "W-RES-004",
        "CalculiX has changed its U1 element",
        "The solver's own forces at the supports of U1 elements balance the "
        "loads and those worked out from the U1 stiffness do not, so the "
        "solver's are given, with no moments. Report it: the U1 matrix in "
        "analysis/user_element_forces.py needs bringing up to date.",
    ),
    MessageKind(
        "W-RES-005",
        "CalculiX's U1 forces are right",
        "The solver's own forces at the supports of U1 elements balance the "
        "loads, which CalculiX 2.23 does not. The reactions given are worked "
        "out from the U1 stiffness and agree with them.",
    ),
    # Plausibility of the results
    MessageKind(
        "W-CHK-001",
        "Member distorts too much",
        "The member bends or stretches by more than 1/100 of its size, "
        "leaving out how it moves as a whole. It is probably not connected or "
        "supported as intended: look at its connections and supports first.",
    ),
    MessageKind(
        "W-CHK-002",
        "Displacement too large",
        "A displacement is more than 5 % of the size of the model, so the "
        "model is probably a mechanism. Check the supports and the "
        "connections between members.",
    ),
]

KINDS: Dict[str, MessageKind] = {kind.code: kind for kind in _KINDS}


def warning(
    code: str,
    message: str,
    *,
    domain_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    ifc_guids: Iterable[str] = (),
) -> Dict[str, Any]:
    """A warning in the form of ``result["warnings"]``.

    Args:
        code: Its code, which must be in ``KINDS``.
        message: What was found in this model, with counts and the first few
            ids; ``KINDS[code].explanation`` says what it means in general.
        domain_id: The one entity it is about, if there is one.
        entity_type: The kind of that entity.
        ifc_guids: The IFC GlobalIds of every entity it is about.

    Raises:
        KeyError: For a code that is not registered.
    """
    kind = KINDS[code]
    return {
        "code": code,
        "title": kind.title,
        "message": message,
        "severity": "warning",
        "entity_type": entity_type,
        "ccx_id": None,
        "domain_id": domain_id,
        "ifc_guids": list(ifc_guids),
    }


def guids_of(model: Any, ids: Iterable[str]) -> List[str]:
    """The IFC GlobalIds of the members, connections and loads with these ids.

    An id the model does not know is given as it is: most are GlobalIds
    already.
    """
    entities = {m.id: m for m in getattr(model, "members", [])}
    entities.update({c.id: c for c in getattr(model, "connections", [])})
    guids = []
    for i in ids:
        entity = entities.get(i)
        guid = getattr(entity, "ifc_guid", None) if entity is not None else None
        guids.append(guid or str(i).split("#")[0])
    return guids


def record_warning(model: Any, code: str, message: str, **kwargs: Any) -> None:
    """Log a warning and put it on the model for ``result["warnings"]``."""
    logger.warning(f"[{code}] {message}")
    if not hasattr(model, "analysis_warnings"):
        model.analysis_warnings = []
    model.analysis_warnings.append(warning(code, message, **kwargs))


def render_markdown() -> str:
    """The list of warnings as ``docs/messages.md`` has it."""
    lines: List[str] = [
        "# Warnings",
        "",
        "<!-- Written by python -m ifc_structural_mechanics.utils.messages;"
        " do not edit. -->",
        "",
        "Every warning the analysis gives has a code, which the command line "
        'prints and `result["warnings"]` of `analyze_ifc()` carries as '
        "`code`: W for a warning, the stage of the analysis it comes from, "
        "and a number. Within a stage the warnings most likely to be met come "
        "first. The message itself says what was found in the model; what "
        "follows says what it means and what to do.",
        "",
    ]
    for stage, name in STAGES.items():
        lines += [f"## {name}", ""]
        for kind in _KINDS:
            if kind.code.split("-")[1] != stage:
                continue
            lines += [
                f"### {kind.code}: {kind.title}",
                "",
                kind.explanation,
                "",
            ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_markdown(), end="")
