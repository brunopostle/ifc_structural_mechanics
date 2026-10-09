"""Second moments of area for open sections, checked against hand calculations.

Convention: y runs across the width (IFC profile X), z up the depth (IFC profile
Y). ``moment_of_inertia_y`` resists bending in the depth direction.
"""

import pytest

from ifc_structural_mechanics.domain.property import Section


def _section(section_type: str, dimensions: dict) -> Section:
    return Section("s", "s", section_type, 1.0, dimensions)


def test_i_section():
    """200 x 400 I, 10 web, 20 flanges."""
    section = Section.create_i_section(
        id="s",
        name="s",
        width=0.2,
        height=0.4,
        web_thickness=0.01,
        flange_thickness=0.02,
    )
    # Iy = [b h^3 - (b - tw)(h - 2 tf)^3] / 12
    assert section.moment_of_inertia_y == pytest.approx(3.279467e-4, rel=1e-5)
    # Iz = [2 tf b^3 + (h - 2 tf) tw^3] / 12
    assert section.moment_of_inertia_z == pytest.approx(2.669667e-5, rel=1e-5)


def test_t_section():
    """200 flange x 300 deep T, 10 web, 20 flange."""
    section = Section.create_t_section(
        id="s",
        name="s",
        width=0.2,
        height=0.3,
        web_thickness=0.01,
        flange_thickness=0.02,
    )
    assert section.moment_of_inertia_y == pytest.approx(5.54855e-5, rel=1e-4)
    assert section.moment_of_inertia_z == pytest.approx(1.33567e-5, rel=1e-4)


def test_l_section_about_geometric_axes():
    """100 x 150 x 10 angle, about centroidal axes parallel to the legs."""
    section = _section("l", {"width": 0.1, "height": 0.15, "thickness": 0.01})
    assert section.moment_of_inertia_y == pytest.approx(5.57625e-6, rel=1e-4)
    assert section.moment_of_inertia_z == pytest.approx(2.02625e-6, rel=1e-4)


def test_c_section():
    """100 x 300 channel, 10 web, 15 flanges."""
    section = _section(
        "c",
        {
            "width": 0.1,
            "height": 0.3,
            "web_thickness": 0.01,
            "flange_thickness": 0.015,
        },
    )
    assert section.moment_of_inertia_y == pytest.approx(7.73775e-5, rel=1e-4)
    assert section.moment_of_inertia_z == pytest.approx(5.39995e-6, rel=1e-4)


def test_inertia_of_rectangles_single_rectangle():
    """One b x h rectangle gives b h^3 / 12 and h b^3 / 12, no product term."""
    i_y, i_z, i_yz = Section._inertia_of_rectangles([(0.0, 0.2, 0.0, 0.4)])
    assert i_y == pytest.approx(0.2 * 0.4**3 / 12)
    assert i_z == pytest.approx(0.4 * 0.2**3 / 12)
    assert i_yz == pytest.approx(0.0, abs=1e-18)
