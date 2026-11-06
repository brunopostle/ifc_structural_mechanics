"""Compare building elements with the structural members that idealise them.

A structural member is linked to the building element it stands for by an
``IfcRelAssignsToProduct``. The specification gives no direction:
``ifcopenshell.api.structural.assign_product`` and homemaker-addon make the
member the ``RelatingProduct``, and either way round is read here (94g.33).

``check_idealisation()`` reports, as warnings with ``W-BLD`` codes, where a
member and its element disagree: where the member lies, how far it reaches,
its section, its material, a surface member's thickness, and elements that
carry load with no member, members with no element. It does not analyse.

The query functions under it (``element_member_pairs()``,
``members_of_element()``, ``elements_of_member()``, ``reference_points()``)
are what an ``ifcopenshell.util.structural`` could offer (issue 9866).
"""

import logging
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.unit
import numpy as np
from scipy.spatial import ConvexHull

from ..utils.messages import warning
from .entity_identifier import (
    face_loops,
    get_item_transformation,
    get_representation,
    transform_vectors,
)

logger = logging.getLogger(__name__)

#: Building elements that may carry load, so are expected to have a member
#: unless their Pset_<Class>Common.LoadBearing is false
LOAD_BEARING_CLASSES = (
    "IfcBeam",
    "IfcColumn",
    "IfcMember",
    "IfcSlab",
    "IfcWall",
    "IfcPlate",
    "IfcFooting",
    "IfcPile",
    "IfcRoof",
    "IfcStair",
    "IfcRamp",
)

#: How far, in metres, a point well inside a member may lie outside its
#: element's body
DEFAULT_TOLERANCE = 0.05

#: The share by which a member's length or area may differ from its element's
EXTENT_RATIO = 1.2

#: How many ids a message names before "and n more"
_FIRST_IDS = 3

#: A direction for ray parity that no axis-aligned edge or face lies along
_RAY = np.array([1.0, 0.0123456, 0.00654321])
_RAY /= np.linalg.norm(_RAY)


# --- Queries --------------------------------------------------------------


def element_member_pairs(
    ifc: ifcopenshell.file,
) -> List[Tuple[ifcopenshell.entity_instance, ifcopenshell.entity_instance]]:
    """Every (structural member, building element) an IfcRelAssignsToProduct links.

    Either may be the RelatingProduct. A pair is listed once.
    """
    pairs = []
    seen = set()
    for relation in ifc.by_type("IfcRelAssignsToProduct"):
        relating = relation.RelatingProduct
        for related in relation.RelatedObjects or ():
            for member, element in ((relating, related), (related, relating)):
                if (
                    member.is_a("IfcStructuralMember")
                    and element.is_a("IfcElement")
                    and (member.id(), element.id()) not in seen
                ):
                    seen.add((member.id(), element.id()))
                    pairs.append((member, element))
    return pairs


def members_of_element(element) -> List[ifcopenshell.entity_instance]:
    """The structural members linked to a building element, either way round."""
    return [
        member
        for member, other in element_member_pairs(element.file)
        if other == element
    ]


def elements_of_member(member) -> List[ifcopenshell.entity_instance]:
    """The building elements a structural member is linked to, either way round."""
    return [
        element
        for other, element in element_member_pairs(member.file)
        if other == member
    ]


def reference_points(member, length_scale: float = 1.0) -> Optional[Dict[str, Any]]:
    """A member's reference geometry in world coordinates, in metres.

    Returns:
        ``{"kind": "edge", "points": [start, end]}`` for a curve member,
        ``{"kind": "face", "points": outline, "holes": [...]}`` for a surface
        member, through the member's placement; None when it has no edge or
        face to read.

    Raises:
        ValueError: If its face cannot be read (``face_loops()``).
    """
    transformation = get_item_transformation(member, length_scale)
    if member.is_a("IfcStructuralCurveMember"):
        representation = get_representation(member, "Edge")
        item = representation.Items[0] if representation else None
        if item is None or not item.is_a("IfcEdge"):
            return None
        points = [
            _coordinates(vertex.VertexGeometry, length_scale)
            for vertex in (item.EdgeStart, item.EdgeEnd)
        ]
        if any(point is None for point in points):
            return None
        return {"kind": "edge", "points": transform_vectors(points, transformation)}
    if member.is_a("IfcStructuralSurfaceMember"):
        representation = get_representation(member, "Face")
        item = representation.Items[0] if representation else None
        if item is None or not item.is_a("IfcFace"):
            return None
        outline, holes = face_loops(item, length_scale)
        return {
            "kind": "face",
            "points": transform_vectors(outline, transformation),
            "holes": [transform_vectors(hole, transformation) for hole in holes],
        }
    return None


def _coordinates(point, length_scale: float) -> Optional[List[float]]:
    coordinates = getattr(point, "Coordinates", None)
    if coordinates is None:
        return None
    return [float(c) * length_scale for c in coordinates] + [0.0] * (
        3 - len(coordinates)
    )


# --- Geometry -------------------------------------------------------------


def _body(element, settings) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """The element's body as world-coordinate triangles, in metres."""
    if not element.Representation:
        return None
    shape = ifcopenshell.geom.create_shape(settings, element)
    vertices = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3)
    faces = np.array(shape.geometry.faces, dtype=int).reshape(-1, 3)
    if not len(faces):
        return None
    return vertices, faces


def _inside(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Whether each point is inside a closed triangulated body (ray parity)."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    e1, e2 = b - a, c - a
    h = np.cross(_RAY, e2)
    det = np.einsum("ij,ij->i", e1, h)
    usable = np.abs(det) > 1e-14
    det = np.where(usable, det, 1.0)
    result = []
    for point in points:
        s = point - a
        u = np.einsum("ij,ij->i", s, h) / det
        q = np.cross(s, e1)
        v = (q @ _RAY) / det
        t = np.einsum("ij,ij->i", e2, q) / det
        hits = usable & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-12)
        result.append(bool(np.count_nonzero(hits) % 2))
    return np.array(result)


def _distance_to_triangles(point: np.ndarray, triangles: np.ndarray) -> float:
    """The distance from a point to the nearest of some triangles."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    normal = np.cross(b - a, c - a)
    length = np.linalg.norm(normal, axis=1)
    good = length > 1e-14
    normal = normal[good] / length[good, None]
    a, b, c = a[good], b[good], c[good]
    # The foot on the plane, if it falls inside the triangle
    height = np.einsum("ij,ij->i", point - a, normal)
    foot = point - height[:, None] * normal
    inside = np.ones(len(a), dtype=bool)
    for start, end in ((a, b), (b, c), (c, a)):
        side = np.einsum("ij,ij->i", np.cross(end - start, foot - start), normal)
        inside &= side >= -1e-12
    best = np.min(np.abs(height[inside])) if inside.any() else np.inf
    # Else the nearest point of an edge
    for start, end in ((a, b), (b, c), (c, a)):
        edge = end - start
        squared = np.maximum(np.einsum("ij,ij->i", edge, edge), 1e-30)
        t = np.clip(np.einsum("ij,ij->i", point - start, edge) / squared, 0.0, 1.0)
        nearest = start + t[:, None] * edge
        best = min(best, float(np.min(np.linalg.norm(point - nearest, axis=1))))
    return float(best)


def _outside_distance(points: np.ndarray, vertices, faces) -> float:
    """How far the farthest of some points lies outside a body (0 inside)."""
    triangles = vertices[faces]
    inside = _inside(points, triangles)
    return max(
        [0.0]
        + [
            _distance_to_triangles(point, triangles)
            for point, is_inside in zip(points, inside)
            if not is_inside
        ]
    )


def _outside_slab(points: np.ndarray, vertices, normal: np.ndarray) -> float:
    """How far the farthest point lies outside a body taken as a slab.

    The slab is the body's extent across the plane (along ``normal``) and the
    convex hull of its outline in the plane, so an opening in the element (a
    window in a wall whose member has none) is not counted as outside: that
    is a difference of area.
    """
    across = vertices @ normal
    x, y = _plane_axes(normal)
    flat = np.column_stack([vertices @ x, vertices @ y])
    hull = ConvexHull(flat)
    worst = 0.0
    for point in points:
        height = float(point @ normal)
        off_plane = max(0.0, across.min() - height, height - across.max())
        flat_point = np.array([point @ x, point @ y])
        # Each row is a unit outward normal and offset: positive outside
        in_plane = max(
            0.0,
            float(np.max(hull.equations[:, :2] @ flat_point + hull.equations[:, 2])),
        )
        worst = max(worst, float(np.hypot(off_plane, in_plane)))
    return worst


def _volume(vertices, faces) -> float:
    triangles = vertices[faces]
    return abs(
        float(
            np.einsum(
                "ij,ij->i",
                triangles[:, 0],
                np.cross(triangles[:, 1], triangles[:, 2]),
            ).sum()
        )
        / 6.0
    )


def _newell_normal(points: np.ndarray) -> np.ndarray:
    """The normal of a polygon, its length twice the polygon's area."""
    return np.sum(np.cross(points, np.roll(points, -1, axis=0)), axis=0)


def _plane_axes(normal: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    helper = np.array([1.0, 0.0, 0.0])
    if abs(normal @ helper) > 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    x = np.cross(helper, normal)
    x /= np.linalg.norm(x)
    return x, np.cross(normal, x)


def _in_polygon(point: np.ndarray, polygon: np.ndarray) -> bool:
    """Even-odd test in two dimensions."""
    inside = False
    x, y = point
    for (x1, y1), (x2, y2) in zip(polygon, np.roll(polygon, -1, axis=0)):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _points_inside_face(outline: np.ndarray, holes: Sequence[np.ndarray]):
    """Points well inside a face: centroids of corner triples that fall in it.

    Ends and edges of a member often run on into the elements its own element
    stops at (axis to axis); points inside it stand for where it is.
    """
    normal = _newell_normal(outline)
    normal = normal / np.linalg.norm(normal)
    x, y = _plane_axes(normal)
    flat = np.column_stack([outline @ x, outline @ y])
    flat_holes = [np.column_stack([hole @ x, hole @ y]) for hole in holes]
    candidates = [outline.mean(axis=0)] + [
        (outline[i] + outline[(i + 1) % len(outline)] + outline[(i + 2) % len(outline)])
        / 3.0
        for i in range(len(outline))
    ]
    kept = []
    for point in candidates:
        flat_point = np.array([point @ x, point @ y])
        if _in_polygon(flat_point, flat) and not any(
            _in_polygon(flat_point, hole) for hole in flat_holes
        ):
            kept.append(point)
    return np.array(kept)


# --- Materials and sections -----------------------------------------------


def _material(product):
    return ifcopenshell.util.element.get_material(product, should_skip_usage=True)


def _load_bearing_layers(element, member_materials) -> Tuple[Optional[list], str]:
    """The layers of an element's layer set that carry load, and by which rule.

    Layers with Category 'LoadBearing' (IFC4's recommended value) if any are;
    else those of the member's material; else None: all layers is wrong for a
    wall with plaster on it.
    """
    material = _material(element)
    if material is None or not material.is_a("IfcMaterialLayerSet"):
        return None, "no layer set"
    layers = list(material.MaterialLayers or [])
    marked = [
        layer
        for layer in layers
        if (getattr(layer, "Category", None) or "").lower() == "loadbearing"
    ]
    if marked:
        return marked, "marked LoadBearing"
    names = {m.Name for m in member_materials}
    ids = {m.id() for m in member_materials}
    same = [
        layer
        for layer in layers
        if layer.Material is not None
        and (layer.Material.id() in ids or layer.Material.Name in names)
    ]
    if same:
        return same, "of the member's material"
    return None, "none marked LoadBearing nor of the member's material"


def _materials_of(product) -> list:
    return [m for m in ifcopenshell.util.element.get_materials(product) if m]


def _profiles_of(product) -> list:
    material = _material(product)
    if material is None or not material.is_a("IfcMaterialProfileSet"):
        return []
    return [p.Profile for p in material.MaterialProfiles or () if p.Profile]


_PROFILE_SKIP = {"ProfileType", "ProfileName", "Position"}


def _profile_values(profile, length_scale: float) -> Tuple[str, Tuple]:
    """A profile's class and its dimensions in metres, rounded to 0.1 mm."""
    values = []
    for name, value in profile.get_info(recursive=False).items():
        if name in _PROFILE_SKIP or name in ("id", "type"):
            continue
        value = getattr(value, "wrappedValue", value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append((name, round(float(value) * length_scale, 4)))
        elif isinstance(value, ifcopenshell.entity_instance):
            values.append((name, value.id()))
        else:
            values.append((name, value))
    return profile.is_a(), tuple(values)


def _describe_profile(profile, length_scale: float) -> str:
    kind, values = _profile_values(profile, length_scale)
    numbers = [
        f"{name} {value:g} m" for name, value in values if isinstance(value, float)
    ]
    name = f" '{profile.ProfileName}'" if profile.ProfileName else ""
    return f"{kind}{name} ({', '.join(numbers)})" if numbers else f"{kind}{name}"


# --- The check ------------------------------------------------------------


class _Findings:
    """Findings grouped by code and message, each with the entities concerned."""

    def __init__(self) -> None:
        self.groups: "OrderedDict[Tuple[str, str], list]" = OrderedDict()

    def add(self, code: str, message: str, *entities, detail: str = "") -> None:
        """One case of a finding: the entities (member, element) and its figures."""
        self.groups.setdefault((code, message), []).append(
            ([e.GlobalId for e in entities], detail)
        )

    def warnings(self) -> List[Dict[str, Any]]:
        result = []
        for (code, message), cases in sorted(
            self.groups.items(), key=lambda item: item[0][0]
        ):
            first = "; ".join(
                " / ".join(ids) + (f": {detail}" if detail else "")
                for ids, detail in cases[:_FIRST_IDS]
            )
            more = (
                f" and {len(cases) - _FIRST_IDS} more"
                if len(cases) > _FIRST_IDS
                else ""
            )
            guids: List[str] = []
            for ids, _ in cases:
                guids.extend(i for i in ids if i not in guids)
            result.append(
                warning(
                    code,
                    f"{message}: {len(cases)} ({first}{more}).",
                    ifc_guids=guids,
                )
            )
        return result


def check_idealisation(
    ifc: ifcopenshell.file, tolerance: float = DEFAULT_TOLERANCE
) -> List[Dict[str, Any]]:
    """Compare each building element with the structural members linked to it.

    Args:
        ifc: The file.
        tolerance: How far, in metres, a point well inside a member may lie
            outside its element's body.

    Returns:
        Warnings in the form of ``result["warnings"]``, one per kind of finding
        with the number of pairs or entities and the first few ids (member /
        element for a pair).
    """
    length_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
    findings = _Findings()
    pairs = element_member_pairs(ifc)
    members = list(ifc.by_type("IfcStructuralMember"))
    if not pairs:
        if members:
            findings.add(
                "W-BLD-001",
                "Structural members, none of them linked to a building element "
                "by an IfcRelAssignsToProduct, so nothing was compared",
                *members,
            )
        return findings.warnings()

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    bodies: Dict[int, Any] = {}
    for member, element in pairs:
        if element.id() not in bodies:
            try:
                bodies[element.id()] = _body(element, settings)
            except RuntimeError as error:
                logger.info(f"No body for {element.GlobalId}: {error}")
                bodies[element.id()] = None
        _compare(
            member, element, bodies[element.id()], length_scale, tolerance, findings
        )

    linked_members = {member.id() for member, _ in pairs}
    linked_elements = {element.id() for _, element in pairs}
    for member in members:
        if member.id() not in linked_members:
            findings.add(
                "W-BLD-006", "Structural members linked to no building element", member
            )
    for element in _unlinked_load_bearing(ifc, linked_elements):
        findings.add(
            "W-BLD-005",
            f"{element.is_a()} that may carry load (LoadBearing true or not "
            "given) with no structural member",
            element,
        )
    return findings.warnings()


def _unlinked_load_bearing(ifc, linked: set) -> Iterable:
    """Elements that may carry load, linked to no member, nor their parts or whole."""
    for element in ifc.by_type("IfcElement"):
        if not any(element.is_a(kind) for kind in LOAD_BEARING_CLASSES):
            continue
        if element.id() in linked:
            continue
        if any(other.id() in linked for other in _parts_and_wholes(element)):
            continue
        if ifcopenshell.util.element.get_parts(element):
            # A whole made of parts: the parts are checked themselves
            continue
        load_bearing = ifcopenshell.util.element.get_pset(
            element, f"Pset_{element.is_a()[3:]}Common", "LoadBearing"
        )
        if load_bearing is False:
            continue
        yield element


def _parts_and_wholes(element) -> list:
    found = []
    stack = list(ifcopenshell.util.element.get_parts(element) or [])
    while stack:
        part = stack.pop()
        found.append(part)
        stack.extend(ifcopenshell.util.element.get_parts(part) or [])
    whole = ifcopenshell.util.element.get_aggregate(element)
    while whole is not None:
        found.append(whole)
        whole = ifcopenshell.util.element.get_aggregate(whole)
    return found


def _compare(member, element, body, length_scale, tolerance, findings) -> None:
    """The findings for one member and its element."""
    try:
        reference = reference_points(member, length_scale)
    except ValueError as error:
        findings.add(
            "W-BLD-011",
            f"Members whose geometry cannot be read ({error})",
            member,
            element,
        )
        reference = None
    if reference is None:
        findings.add(
            "W-BLD-011",
            "Members with no edge or face to compare with their element",
            member,
            element,
        )
    elif body is None:
        findings.add(
            "W-BLD-011",
            "Elements with no body to compare with their member",
            member,
            element,
        )
    else:
        _compare_geometry(member, element, reference, body, tolerance, findings)

    member_materials = _materials_of(member)
    _compare_material(member, element, member_materials, findings)
    if member.is_a("IfcStructuralCurveMember"):
        _compare_profile(member, element, length_scale, findings)
    if member.is_a("IfcStructuralSurfaceMember"):
        _compare_thickness(
            member, element, member_materials, reference, body, length_scale, findings
        )


def _compare_geometry(member, element, reference, body, tolerance, findings) -> None:
    vertices, faces = body
    points = np.array(reference["points"], dtype=float)
    if reference["kind"] == "edge":
        axis = points[1] - points[0]
        length = float(np.linalg.norm(axis))
        if length < 1e-6:
            findings.add(
                "W-BLD-010",
                "Curve members of no length (the analysis cannot use them)",
                member,
                element,
            )
            return
        inner = np.array([points[0] + f * axis for f in (0.25, 0.5, 0.75)])
        along = vertices @ (axis / length)
        extent = float(along.max() - along.min())
        what, size, unit = "length", length, "m"
    else:
        holes = [np.array(hole, dtype=float) for hole in reference["holes"]]
        normal = _newell_normal(points)
        area = float(np.linalg.norm(normal)) / 2.0 - sum(
            float(np.linalg.norm(_newell_normal(hole))) / 2.0 for hole in holes
        )
        if area < 1e-9:
            findings.add(
                "W-BLD-010",
                "Surface members of no area (the analysis cannot use them)",
                member,
                element,
            )
            return
        inner = _points_inside_face(points, holes)
        across = vertices @ (normal / np.linalg.norm(normal))
        thickness = float(across.max() - across.min())
        # Its area as a slab of that thickness: openings and outline as built
        extent = _volume(vertices, faces) / thickness if thickness > 1e-9 else 0.0
        what, size, unit = "area", area, "m²"

    if len(inner):
        if reference["kind"] == "edge":
            outside = _outside_distance(inner, vertices, faces)
        else:
            outside = _outside_slab(inner, vertices, normal / np.linalg.norm(normal))
        if outside > tolerance:
            findings.add(
                "W-BLD-007",
                f"Members more than {tolerance:g} m outside their element's body",
                member,
                element,
                detail=f"{outside:.3f} m",
            )
    if extent > 0 and not (1 / EXTENT_RATIO <= size / extent <= EXTENT_RATIO):
        findings.add(
            "W-BLD-008",
            f"Members whose {what} differs from their element's by more than "
            f"{EXTENT_RATIO - 1:.0%}",
            member,
            element,
            detail=f"{size:.3g} against {extent:.3g} {unit}",
        )


def _compare_material(member, element, member_materials, findings) -> None:
    if not member_materials:
        return
    element_materials = _materials_of(element)
    layers, _ = _load_bearing_layers(element, member_materials)
    if layers:
        element_materials = [layer.Material for layer in layers if layer.Material]
    if not element_materials:
        return
    member_names = sorted({m.Name for m in member_materials})
    element_names = sorted({m.Name for m in element_materials})
    same = {m.id() for m in member_materials} & {m.id() for m in element_materials}
    if same or set(member_names) & set(element_names):
        return
    findings.add(
        "W-BLD-002",
        f"Members of {', '.join(map(repr, member_names))} in elements of "
        f"{', '.join(map(repr, element_names))}",
        member,
        element,
    )


def _compare_profile(member, element, length_scale, findings) -> None:
    member_profiles = _profiles_of(member)
    element_profiles = _profiles_of(element)
    if not member_profiles or not element_profiles:
        return
    if {p.id() for p in member_profiles} & {p.id() for p in element_profiles}:
        return
    member_values = {_profile_values(p, length_scale) for p in member_profiles}
    element_values = {_profile_values(p, length_scale) for p in element_profiles}
    if member_values & element_values:
        return
    findings.add(
        "W-BLD-004",
        f"Members of section {_describe_profile(member_profiles[0], length_scale)} "
        f"in elements of {_describe_profile(element_profiles[0], length_scale)}",
        member,
        element,
    )


def _compare_thickness(
    member, element, member_materials, reference, body, length_scale, findings
) -> None:
    if member.Thickness is None:
        return
    thickness = float(member.Thickness) * length_scale
    layers, rule = _load_bearing_layers(element, member_materials)
    if layers:
        expected = sum(float(layer.LayerThickness) for layer in layers) * length_scale
        source = f"its load-bearing layers ({rule})"
    elif rule == "no layer set" and body is not None and reference is not None:
        if reference["kind"] != "face":
            return
        normal = _newell_normal(np.array(reference["points"], dtype=float))
        across = body[0] @ (normal / np.linalg.norm(normal))
        expected = float(across.max() - across.min())
        source = "its body across the member"
    elif rule != "no layer set":
        findings.add(
            "W-BLD-009",
            f"Surface members whose element's load-bearing layers cannot be told "
            f"({rule}), so their Thickness was not compared",
            member,
            element,
        )
        return
    else:
        return
    if abs(thickness - expected) > 1e-3:
        findings.add(
            "W-BLD-003",
            f"Surface members of Thickness {thickness:.3f} m where {source} "
            f"give {expected:.3f} m",
            member,
            element,
        )
