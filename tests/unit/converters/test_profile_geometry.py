"""Area and inertias of rolled sections from their outline (94g.26).

The published values are those of the European and American tables: HEB 160
and IPE 300 (Arcelor), W10X30 (AISC). The tables round to four figures.
"""

import math

import pytest

from ifc_structural_mechanics.converters.profile_geometry import (
    i_shape,
    l_shape,
    outline_properties,
    principal_axes,
    rounded_outline,
    t_shape,
    u_shape,
)

# The area a fillet of radius r adds in a right-angled corner
FILLET = 1 - math.pi / 4


@pytest.mark.parametrize(
    "dimensions, published",
    [
        ((0.160, 0.160, 0.008, 0.013, 0.015), (54.25e-4, 2492e-8, 889.2e-8)),
        ((0.150, 0.300, 0.0071, 0.0107, 0.015), (53.81e-4, 8356e-8, 603.8e-8)),
    ],
    ids=["HEB160", "IPE300"],
)
def test_rolled_i_sections_are_those_of_the_tables(dimensions, published):
    width, depth, web, flange, fillet = dimensions
    found = outline_properties(i_shape(width, depth, web, flange, bottom_fillet=fillet))
    area, strong, weak = published
    assert found.area == pytest.approx(area, rel=5e-4)
    assert found.i_xx == pytest.approx(strong, rel=5e-4)
    assert found.i_yy == pytest.approx(weak, rel=5e-4)
    assert found.centroid == pytest.approx((0.0, 0.0), abs=1e-12)


def test_a_sharp_i_section_is_its_plates():
    found = outline_properties(i_shape(0.16, 0.16, 0.008, 0.013))
    assert found.area == pytest.approx(2 * 0.16 * 0.013 + 0.008 * 0.134)
    web = 0.008 * 0.134**3 / 12
    flanges = 2 * (0.16 * 0.013**3 / 12 + 0.16 * 0.013 * (0.08 - 0.0065) ** 2)
    assert found.i_xx == pytest.approx(web + flanges)


def test_edge_radii_take_area_off_the_flanges():
    sharp = outline_properties(i_shape(0.2, 0.4, 0.01, 0.02))
    rounded = outline_properties(i_shape(0.2, 0.4, 0.01, 0.02, bottom_edge=0.005))
    assert sharp.area - rounded.area == pytest.approx(4 * FILLET * 0.005**2, rel=1e-4)


@pytest.mark.parametrize(
    "outline, fillets",
    [
        (lambda r: t_shape(0.2, 0.2, 0.01, 0.02, fillet=r), 2),
        (lambda r: l_shape(0.1, 0.1, 0.01, fillet=r), 1),
        (lambda r: u_shape(0.2, 0.08, 0.008, 0.012, fillet=r), 2),
    ],
    ids=["T", "L", "U"],
)
def test_fillets_of_the_other_shapes(outline, fillets):
    added = (
        outline_properties(outline(0.008)).area - outline_properties(outline(0)).area
    )
    assert added == pytest.approx(fillets * FILLET * 0.008**2, rel=1e-4)


def test_an_asymmetric_i_section_about_its_own_centroid():
    """A wide bottom flange pulls the centroid down from mid-depth."""
    found = outline_properties(
        i_shape(0.3, 0.4, 0.01, 0.02, top_width=0.1, top_flange_thickness=0.02)
    )
    plates = [  # (area, height of its centre, own inertia)
        (0.3 * 0.02, -0.19, 0.3 * 0.02**3 / 12),
        (0.1 * 0.02, 0.19, 0.1 * 0.02**3 / 12),
        (0.01 * 0.36, 0.0, 0.01 * 0.36**3 / 12),
    ]
    area = sum(a for a, _, _ in plates)
    centre = sum(a * z for a, z, _ in plates) / area
    inertia = sum(i + a * (z - centre) ** 2 for a, z, i in plates)
    assert found.area == pytest.approx(area)
    assert found.centroid[1] == pytest.approx(centre)
    assert found.i_xx == pytest.approx(inertia)


def test_an_equal_angle_has_a_product_of_inertia():
    """L 100 x 100 x 10, sharp: its principal axes are at 45 degrees."""
    found = outline_properties(l_shape(0.1, 0.1, 0.01))
    assert found.i_xx == pytest.approx(found.i_yy)
    assert found.i_xy < 0
    # Principal values of the sharp angle, from its rectangles
    assert found.i_xx + abs(found.i_xy) == pytest.approx(286.6e-8, rel=1e-3)


def test_an_equal_angle_is_turned_45_degrees():
    """Its stiff direction is across the heel: profile y turned towards -x."""
    found = outline_properties(l_shape(0.1, 0.1, 0.01))
    angle, i_1, i_2 = principal_axes(found.i_xx, found.i_yy, found.i_xy)
    assert angle == pytest.approx(math.pi / 4)
    assert i_1 == pytest.approx(found.i_xx + abs(found.i_xy))
    assert i_2 == pytest.approx(found.i_xx - abs(found.i_xy))


@pytest.mark.parametrize("i_xx, i_yy, i_xy", [(3.0, 1.0, -0.8), (1.0, 3.0, 0.5)])
def test_principal_axes_have_no_product_of_inertia(i_xx, i_yy, i_xy):
    angle, i_1, i_2 = principal_axes(i_xx, i_yy, i_xy)
    first = (-math.sin(angle), math.cos(angle))
    second = (math.cos(angle), math.sin(angle))

    def inertia(u, v):
        # ∫ (r.u)(r.v) dA from the tensor about x and y of the profile
        return (
            i_yy * u[0] * v[0] + i_xx * u[1] * v[1] + i_xy * (u[0] * v[1] + u[1] * v[0])
        )

    assert inertia(first, first) == pytest.approx(i_1)
    assert inertia(second, second) == pytest.approx(i_2)
    assert inertia(first, second) == pytest.approx(0.0, abs=1e-12)
    assert i_1 >= i_2
    assert i_1 + i_2 == pytest.approx(i_xx + i_yy)


def test_a_symmetric_section_is_not_turned():
    assert principal_axes(3.0, 1.0, 0.0) == (0.0, 3.0, 1.0)


def test_a_flange_slope_thickens_the_flanges_at_the_web():
    flat = outline_properties(i_shape(0.2, 0.4, 0.01, 0.02))
    sloped = outline_properties(
        i_shape(0.2, 0.4, 0.01, 0.02, bottom_slope=math.atan(0.14))
    )
    # Two triangles on each flange, (b - tw) / 2 long, rising 0.14 of that
    rise = (0.1 - 0.005) * 0.14
    assert sloped.area - flat.area == pytest.approx(4 * (0.1 - 0.005) * rise / 2)


def test_a_radius_that_does_not_fit_is_refused():
    with pytest.raises(ValueError, match="does not fit"):
        rounded_outline([(0, 0, 0), (1, 0, 0), (1, 1, 2.0), (0, 1, 0)])
