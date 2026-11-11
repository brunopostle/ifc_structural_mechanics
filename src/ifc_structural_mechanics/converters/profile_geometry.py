"""The outline of a parameterised profile, and its area and second moments.

A rolled section's fillets, the rounded edges of its flanges and the slope of
tapered flanges are part of its outline, and leaving them out makes an HEB 160
3.2% too flexible (94g.26). The outlines here are IfcOpenShell's own
(``src/ifcgeom/mapping/Ifc*ShapeProfileDef.cpp``): the same corners, each
rounded with an arc tangent to both its edges, so the section analysed is the
one Bonsai draws. The arcs are divided finely (``ARC_SEGMENTS``); IfcOpenShell's
own triangulation draws a fillet as one chord, 0.6% too much area for an HEB.

Coordinates are those of the profile, in metres: x across its width (the
member's local y), y up its depth (the member's local z), origin at the middle
of the bounding box, as IFC places these profiles.

IFC does not say in words where a tapered flange's thickness is measured, and
IfcOpenShell measures it at the flange's edge for an I section and nearer the
web for the others; ``has_slope`` lets the caller say so.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

#: Straight pieces per rounded corner: a quarter circle's chords then miss
#: 2.3e-5 of a fillet's own area, far below any rolling tolerance
ARC_SEGMENTS = 256

Corner = Tuple[float, float, float]  # x, y, radius (0 for a sharp corner)


@dataclass(frozen=True)
class OutlineProperties:
    """Area and second moments of an outline, about its centroid."""

    area: float
    centroid: Tuple[float, float]
    #: Second moment about the axis along x (bending in the depth): ∫ y² dA
    i_xx: float
    #: Second moment about the axis along y: ∫ x² dA
    i_yy: float
    #: Product of inertia: ∫ x y dA
    i_xy: float


def rounded_outline(corners: Sequence[Corner]) -> List[Tuple[float, float]]:
    """A closed polygon through some corners, each rounded with its radius.

    The arc at a corner is tangent to both edges that meet there, as
    IfcOpenShell's ``fillet_loop()`` makes it.

    Raises:
        ValueError: If a radius is larger than its edges allow.
    """
    count = len(corners)
    points: List[Tuple[float, float]] = []
    for index, (x, y, radius) in enumerate(corners):
        if not radius or radius <= 0.0:
            points.append((x, y))
            continue
        before = corners[index - 1]
        after = corners[(index + 1) % count]
        to_before = _unit(before[0] - x, before[1] - y)
        to_after = _unit(after[0] - x, after[1] - y)
        cosine = max(
            -1.0, min(1.0, to_before[0] * to_after[0] + to_before[1] * to_after[1])
        )
        angle = math.acos(cosine)
        inset = radius / math.tan(angle / 2.0)
        if (
            inset > _length(before[0] - x, before[1] - y) + 1e-12
            or inset > _length(after[0] - x, after[1] - y) + 1e-12
        ):
            raise ValueError(
                f"A radius of {radius:g} m does not fit the corner at "
                f"({x:g}, {y:g}) m of the profile."
            )
        start = (x + to_before[0] * inset, y + to_before[1] * inset)
        end = (x + to_after[0] * inset, y + to_after[1] * inset)
        bisector = _unit(to_before[0] + to_after[0], to_before[1] + to_after[1])
        distance = radius / math.sin(angle / 2.0)
        centre = (x + bisector[0] * distance, y + bisector[1] * distance)
        first = math.atan2(start[1] - centre[1], start[0] - centre[0])
        last = math.atan2(end[1] - centre[1], end[0] - centre[0])
        sweep = last - first
        # The arc turns through pi - angle, the short way round
        while sweep > math.pi:
            sweep -= 2 * math.pi
        while sweep < -math.pi:
            sweep += 2 * math.pi
        for step in range(ARC_SEGMENTS + 1):
            theta = first + sweep * step / ARC_SEGMENTS
            points.append(
                (
                    centre[0] + radius * math.cos(theta),
                    centre[1] + radius * math.sin(theta),
                )
            )
    return points


def outline_properties(points: Sequence[Tuple[float, float]]) -> OutlineProperties:
    """Area, centroid and centroidal second moments of a simple polygon (Green)."""
    area = s_x = s_y = i_xx = i_yy = i_xy = 0.0
    count = len(points)
    for index in range(count):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % count]
        cross = x0 * y1 - x1 * y0
        area += cross / 2.0
        s_x += (x0 + x1) * cross / 6.0
        s_y += (y0 + y1) * cross / 6.0
        i_xx += (y0 * y0 + y0 * y1 + y1 * y1) * cross / 12.0
        i_yy += (x0 * x0 + x0 * x1 + x1 * x1) * cross / 12.0
        i_xy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * cross / 24.0
    if area < 0:  # clockwise
        area, s_x, s_y, i_xx, i_yy, i_xy = (
            -area,
            -s_x,
            -s_y,
            -i_xx,
            -i_yy,
            -i_xy,
        )
    if area <= 0:
        raise ValueError("The profile's outline has no area.")
    cx, cy = s_x / area, s_y / area
    return OutlineProperties(
        area=area,
        centroid=(cx, cy),
        i_xx=i_xx - area * cy * cy,
        i_yy=i_yy - area * cx * cx,
        i_xy=i_xy - area * cx * cy,
    )


def principal_axes(i_xx: float, i_yy: float, i_xy: float) -> Tuple[float, float, float]:
    """The principal second moments of a section and how far they are turned.

    ``i_xx``, ``i_yy`` and ``i_xy`` are about centroidal axes along x and y of
    the profile (``OutlineProperties``). The first principal direction is the
    profile's y turned by the angle returned, positive from y towards -x: the
    member's local z turned right-handed about its x. Along it the section is
    stiffest, and across it least stiff; the product of inertia about them is
    zero. An angle has one 45 degrees from its legs if they are equal.

    Returns:
        The angle in radians, in (-pi/2, pi/2], then the second moment for
        bending along the first direction and that along the second
    """
    mean = (i_xx + i_yy) / 2.0
    radius = math.hypot((i_xx - i_yy) / 2.0, i_xy)
    if radius == 0.0:
        return 0.0, i_xx, i_yy
    angle = math.atan2(-2.0 * i_xy, i_xx - i_yy) / 2.0
    return angle, mean + radius, mean - radius


def i_shape(
    bottom_width: float,
    depth: float,
    web_thickness: float,
    bottom_flange_thickness: float,
    top_width: Optional[float] = None,
    top_flange_thickness: Optional[float] = None,
    bottom_fillet: float = 0.0,
    top_fillet: Optional[float] = None,
    bottom_edge: float = 0.0,
    top_edge: Optional[float] = None,
    bottom_slope: float = 0.0,
    top_slope: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """IfcIShapeProfileDef, or IfcAsymmetricIShapeProfileDef with the top given.

    Slopes in radians; a flange's thickness is at its edge, as IfcOpenShell
    draws it.
    """
    xb = bottom_width / 2.0
    xt = (top_width if top_width is not None else bottom_width) / 2.0
    y = depth / 2.0
    d1 = web_thickness / 2.0
    ftb = bottom_flange_thickness
    ftt = top_flange_thickness if top_flange_thickness is not None else ftb
    fb = bottom_fillet
    ft = top_fillet if top_fillet is not None else fb
    eb = bottom_edge
    et = top_edge if top_edge is not None else eb
    dyb = (xb - d1) * math.tan(bottom_slope)
    dyt = (xt - d1) * math.tan(top_slope if top_slope is not None else bottom_slope)
    return rounded_outline(
        [
            (-xb, -y, 0.0),
            (xb, -y, 0.0),
            (xb, -y + ftb, eb),
            (d1, -y + ftb + dyb, fb),
            (d1, y - ftt - dyt, ft),
            (xt, y - ftt, et),
            (xt, y, 0.0),
            (-xt, y, 0.0),
            (-xt, y - ftt, et),
            (-d1, y - ftt - dyt, ft),
            (-d1, -y + ftb + dyb, fb),
            (-xb, -y + ftb, eb),
        ]
    )


def t_shape(
    depth: float,
    flange_width: float,
    web_thickness: float,
    flange_thickness: float,
    fillet: float = 0.0,
    flange_edge: float = 0.0,
    web_edge: float = 0.0,
    web_slope: float = 0.0,
    flange_slope: float = 0.0,
) -> List[Tuple[float, float]]:
    """IfcTShapeProfileDef, flange at the top, as IfcOpenShell draws it."""
    y = depth / 2.0
    x = flange_width / 2.0
    d1 = web_thickness
    d2 = flange_thickness
    dy1 = (x / 2.0 - d1) * math.tan(flange_slope)
    dy2 = x / 2.0 * math.tan(flange_slope)
    dx1 = (y - d2) * math.tan(web_slope)
    dx2 = y * math.tan(web_slope)
    if web_slope or flange_slope:
        xx, xy = _intersection(
            (d1 / 2.0 - dx2, -y),
            (d1 / 2.0 + dx1, y - d2),
            (x, y - d2 + dy2),
            (d1 / 2.0, y - d2 - dy1),
        )
    else:
        xx, xy = d1 / 2.0, y - d2
    return rounded_outline(
        [
            (d1 / 2.0 - dx2, -y, web_edge),
            (xx, xy, fillet),
            (x, y - d2 + dy2, flange_edge),
            (x, y, 0.0),
            (-x, y, 0.0),
            (-x, y - d2 + dy2, flange_edge),
            (-xx, xy, fillet),
            (-d1 / 2.0 + dx2, -y, web_edge),
        ]
    )


def l_shape(
    depth: float,
    width: float,
    thickness: float,
    fillet: float = 0.0,
    edge: float = 0.0,
    leg_slope: float = 0.0,
) -> List[Tuple[float, float]]:
    """IfcLShapeProfileDef, as IfcOpenShell draws it."""
    y = depth / 2.0
    x = width / 2.0
    d = thickness
    dy1 = math.tan(leg_slope) * x
    dy2 = math.tan(leg_slope) * (x - d)
    dx1 = math.tan(leg_slope) * y
    dx2 = math.tan(leg_slope) * (y - d)
    if leg_slope:
        xx, xy = _intersection(
            (x, -y + d - dy1),
            (-x + d, -y + d + dy2),
            (-x + d - dx1, y),
            (-x + d + dx2, -y + d),
        )
    else:
        xx, xy = -x + d, -y + d
    return rounded_outline(
        [
            (-x, -y, 0.0),
            (x, -y, 0.0),
            (x, -y + d - dy1, edge),
            (xx, xy, fillet),
            (-x + d - dx1, y, edge),
            (-x, y, 0.0),
        ]
    )


def u_shape(
    depth: float,
    flange_width: float,
    web_thickness: float,
    flange_thickness: float,
    fillet: float = 0.0,
    edge: float = 0.0,
    flange_slope: float = 0.0,
) -> List[Tuple[float, float]]:
    """IfcUShapeProfileDef, web on the left, as IfcOpenShell draws it."""
    y = depth / 2.0
    x = flange_width / 2.0
    d1 = web_thickness
    d2 = flange_thickness
    dy1 = (x - d1) * math.tan(flange_slope)
    dy2 = x * math.tan(flange_slope)
    return rounded_outline(
        [
            (-x, -y, 0.0),
            (x, -y, 0.0),
            (x, -y + d2 - dy2, edge),
            (-x + d1, -y + d2 + dy1, fillet),
            (-x + d1, y - d2 - dy1, fillet),
            (x, y - d2 + dy2, edge),
            (x, y, 0.0),
            (-x, y, 0.0),
        ]
    )


def _unit(x: float, y: float) -> Tuple[float, float]:
    length = _length(x, y)
    return x / length, y / length


def _length(x: float, y: float) -> float:
    return math.hypot(x, y)


def _intersection(a0, a1, b0, b1) -> Tuple[float, float]:
    """Where the line through a0 and a1 meets the one through b0 and b1."""
    p = (a1[1] - a0[1], a0[0] - a1[0])
    q = (b1[1] - b0[1], b0[0] - b1[0])
    c1 = p[0] * a0[0] + p[1] * a0[1]
    c2 = q[0] * b0[0] + q[1] * b0[1]
    det = p[0] * q[1] - q[0] * p[1]
    if abs(det) < 1e-12:
        raise ValueError("The slopes of the profile make its faces parallel.")
    return (q[1] * c1 - p[1] * c2) / det, (p[0] * c2 - q[0] * c1) / det
