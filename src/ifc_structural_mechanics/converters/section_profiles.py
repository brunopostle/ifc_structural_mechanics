"""Registry of supported beam cross-section profiles.

Defines which section types exist, which CalculiX element/section format they
use, and how to format the *BEAM SECTION data line for native types.

**Adding a new section type** requires touching exactly two places:
  1. Add an entry to ``SECTION_REGISTRY`` here.
  2. Add an IFC profile extraction handler in
     ``ifc/properties_extractor.py`` and ``ifc/members_extractor.py``.

No other files need to change — the writer and validator query this registry.

Element strategy
----------------
* **Native** (``use_general=False``): a CalculiX beam element with
  ``SECTION=RECT``. Only the solid rectangle is written this way, with one
  shear modulus lowered so that it twists as it should
  (``rectangle_shear_moduli``). CalculiX
  also has CIRC, PIPE and BOX, but PIPE and BOX exist for B32R alone (B31
  rejects them) and a PIPE cantilever measured 83 % too flexible with the
  weight of a solid bar, so they are not used.
* **General** (``use_general=True``): every other shape. The writer analyses
  it from the domain Section's A, Iy, Iz and shear areas, either as a native
  beam element with a rectangle of the same stiffness (``equivalent_rectangle``)
  or, in a model made of such members only, as a U1 element with
  ``SECTION=GENERAL``.

Supported IFC profile types per domain section_type
----------------------------------------------------
rectangular         IfcRectangleProfileDef
circular            IfcCircleProfileDef (solid)
hollow_circular     IfcCircleHollowProfileDef
hollow_rectangular  IfcRectangleHollowProfileDef
i                   IfcIShapeProfileDef, IfcAsymmetricIShapeProfileDef
l                   IfcLShapeProfileDef
t                   IfcTShapeProfileDef
c                   IfcUShapeProfileDef
u                   IfcUShapeProfileDef  (future)
z                   IfcZShapeProfileDef  (future)
"""

from typing import Callable, Dict, NamedTuple, Optional, Tuple


class SectionProfile(NamedTuple):
    """CalculiX *BEAM SECTION configuration for one cross-section type.

    Attributes:
        use_general: If True, use U1 element with ``SECTION=GENERAL``.
            The writer derives A, I11, I22, k_s from the domain Section object.
            If False, use B31 element with the native ``ccx_keyword``.
        ccx_keyword: The ``SECTION=`` value for B31 native types (e.g. "RECT").
            None when use_general is True.
        format_data_line: Callable that formats the first *BEAM SECTION data
            line from the section's ``dimensions`` dict.  None for GENERAL types.
    """

    use_general: bool
    ccx_keyword: Optional[str]
    format_data_line: Optional[Callable[[dict], str]]


# ---------------------------------------------------------------------------
# B31 native formatters
# ---------------------------------------------------------------------------


def _fmt_rect(d: dict) -> str:
    # CalculiX RECT: a (along the section 1 direction, depth), b (width).
    # The writer gives the IFC local z as the 1 direction, and the IFC profile
    # depth (YDim) lies along local z.
    return f"{d['height']:.6e}, {d['width']:.6e}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Maps domain ``section_type`` strings (lower-case) to their CalculiX format.
#: This is the single source of truth consulted by the writer and by any
#: code that needs to know whether a section type is supported.
SECTION_REGISTRY: Dict[str, SectionProfile] = {
    # ---- native: the one shape CalculiX's beam expansion gets right ----
    "rectangular": SectionProfile(False, "RECT", _fmt_rect),
    # ---- every other shape: an equivalent rectangle, or U1 + GENERAL ----
    # Analysed from A, Iy, Iz and the shear areas of the domain Section, so a
    # new type needs those computed in domain/property.py and an extraction
    # handler; nothing here or in the writer.
    "circular": SectionProfile(True, None, None),  # IfcCircleProfileDef
    "hollow_circular": SectionProfile(True, None, None),  # IfcCircleHollowProfileDef
    "hollow_rectangular": SectionProfile(True, None, None),
    "i": SectionProfile(True, None, None),  # IfcIShapeProfileDef
    "i_asymmetric": SectionProfile(True, None, None),  # IfcAsymmetricIShapeProfileDef
    "l": SectionProfile(True, None, None),  # IfcLShapeProfileDef
    "t": SectionProfile(True, None, None),  # IfcTShapeProfileDef
    "c": SectionProfile(True, None, None),  # IfcUShapeProfileDef
    "u": SectionProfile(True, None, None),  # IfcUShapeProfileDef
    "z": SectionProfile(True, None, None),  # IfcZShapeProfileDef
}


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def uses_user_element(section_type: Optional[str]) -> bool:
    """Return True if this section type requires a U1 user element (GENERAL).

    Unknown section types are treated as GENERAL (safe fallback).
    """
    if not section_type:
        return False
    profile = SECTION_REGISTRY.get(section_type.lower())
    # Unknown types use GENERAL (conservative — avoids silent RECT approximation)
    return profile.use_general if profile else True


def equivalent_rectangle(
    area: float, inertia_1: float, inertia_2: float
) -> Tuple[float, float, float]:
    """Return the rectangle that stands in for a section CalculiX has no shape for.

    A rectangle ``a`` x ``b`` whose material is scaled by ``factor`` has the
    section's axial stiffness and both bending stiffnesses::

        factor * a * b       = area
        factor * b * a**3/12 = inertia_1
        factor * a * b**3/12 = inertia_2

    so ``a`` and ``b`` are the section's radii of gyration times the square
    root of twelve. Scaling the density by the same factor keeps the weight.
    Shear and torsion are left to the material, see
    ``equivalent_shear_moduli``.

    Args:
        area: Cross-section area.
        inertia_1: Second moment of area resisting loads along the section's
            1 direction (``a`` is measured along it).
        inertia_2: Second moment of area about the other axis.

    Returns:
        ``(a, b, factor)``; multiply the elastic modulus and the density by
        ``factor``.

    Raises:
        ValueError: If any of the three properties is not positive.
    """
    if not (area > 0 and inertia_1 > 0 and inertia_2 > 0):
        raise ValueError(
            "equivalent rectangle needs positive area and inertias, got "
            f"A={area}, I1={inertia_1}, I2={inertia_2}"
        )
    a = (12.0 * inertia_1 / area) ** 0.5
    b = (12.0 * inertia_2 / area) ** 0.5
    return a, b, area / (a * b)


#: Section types whose equivalent rectangle is given the section's torsional
#: stiffness, at the expense of its shear stiffness: the closed and the solid
#: ones. An open section cannot be treated this way, its torsional stiffness
#: is tens of times lower than anything that leaves it able to carry shear.
TORSION_MATCHED_SECTIONS = frozenset(
    {"circular", "hollow_circular", "hollow_rectangular"}
)


def expanded_rectangle_torsion_stiffness(
    a: float, b: float, modulus_12: float, modulus_13: float
) -> float:
    """Return the torsional stiffness CalculiX gives an ``a`` x ``b`` beam.

    CalculiX expands a beam into one solid element across the section, and
    the only warping that element can take is ``x2 * x3``. Minimising the
    strain energy over its size gives ``4 P Q / (P + Q)``, with
    ``P = G12 a b**3 / 12`` and ``Q = G13 b a**3 / 12``. Measured twist
    agrees with this to three figures. It is not Saint-Venant's value: an
    isotropic square comes out as ``G a**4 / 6``, 18.5 % above
    ``0.1406 G a**4``, and the excess fades as the rectangle gets narrower.

    Args:
        a: Dimension along the section's 1 direction.
        b: The other dimension.
        modulus_12: Shear modulus of the plane of the member axis and ``a``.
        modulus_13: Shear modulus of the plane of the member axis and ``b``.

    Returns:
        Torque per unit rate of twist.
    """
    p = modulus_12 * a * b**3 / 12.0
    q = modulus_13 * b * a**3 / 12.0
    return 4.0 * p * q / (p + q)


def equivalent_shear_moduli(
    a: float,
    b: float,
    shear_modulus: float,
    shear_area_1: float,
    shear_area_2: float,
    torsion_constant: Optional[float] = None,
) -> Tuple[float, float, float]:
    """Return the shear moduli of an equivalent rectangle's material.

    Two moduli cannot give a rectangle two shear areas and a torsion constant.
    Without ``torsion_constant`` they match shear::

        G12 * a * b = shear_modulus * shear_area_1
        G13 * a * b = shear_modulus * shear_area_2

    The rectangle's shear area is its whole area here, not 5/6 of it. That is
    a calibration: with 5/6 the shear deflection of the I-section benchmarks
    came out 12 to 18 % short. An isotropic rectangle in CalculiX does follow
    5/6; these orthotropic ones do not.

    With ``torsion_constant`` both are then scaled by one number so that
    ``expanded_rectangle_torsion_stiffness`` equals ``shear_modulus *
    torsion_constant``. Torsion is then right and shear stiffness is off by
    that number in both directions (1.1 for a round bar, 1.4 for a typical
    box, 1.9 for a thin tube).

    Args:
        a: Rectangle dimension along the section's 1 direction.
        b: The other dimension.
        shear_modulus: Shear modulus of the real material.
        shear_area_1: Shear area for loads along the 1 direction.
        shear_area_2: Shear area for loads along the other direction.
        torsion_constant: The section's torsion constant, to match torsion.

    Returns:
        ``(G12, G13, scale)``; ``scale`` is the factor by which the shear
        stiffness used exceeds the section's (1.0 when shear is matched).
    """
    modulus_12 = shear_modulus * shear_area_1 / (a * b)
    modulus_13 = shear_modulus * shear_area_2 / (a * b)
    if not torsion_constant or torsion_constant <= 0:
        return modulus_12, modulus_13, 1.0
    scale = (
        shear_modulus
        * torsion_constant
        / expanded_rectangle_torsion_stiffness(a, b, modulus_12, modulus_13)
    )
    return modulus_12 * scale, modulus_13 * scale, scale


#: Shear coefficient of a solid rectangle. CalculiX's expanded beam, with no
#: Poisson's ratio, shears with its whole area (as if this were 1), so the
#: moduli it is given are this share of the material's (aiz.101).
RECTANGLE_SHEAR_COEFFICIENT = 5.0 / 6.0


def rectangle_shear_moduli(
    a: float, b: float, shear_modulus: float, torsion_constant: float
) -> Tuple[float, float]:
    """Return the shear moduli that make a solid rectangle shear and twist right.

    CalculiX's expanded rectangle, with the Poisson's ratio of zero beams
    have, shears with its whole area rather than 5/6 of it, and is too stiff
    in torsion (see ``expanded_rectangle_torsion_stiffness``): 18.5 % for a
    square. The modulus of the plane of the member axis and ``a``, the
    depth, is 5/6 of the material's, so bending and shear along the depth
    are those of Timoshenko's beam. The other one is set so that the
    torsional stiffness is ``shear_modulus * torsion_constant``::

        P = G12 a b**3 / 12
        Q = G J P / (4 P - G J)        G13 = 12 Q / (b a**3)

    It then comes out within a few percent of 5/6 of the material's for
    sections up to twice as deep as wide (0.85 G for a square, 0.87 G for
    one twice as wide as deep, 0.98 G for one twice as deep). A deeper
    section would need more than the material's own modulus, and soon
    more than any: ``G13`` is then held at ``G`` and ``G12`` raised
    instead until torsion is right, so shear along the depth is stiffer
    than Timoshenko's by ``G12 / (5/6 G)`` (1.04 at 3:1, 1.09 at 5:1, 1.14
    at 10:1, never the 1.2 of the material's modulus).

    Args:
        a: Dimension along the section's 1 direction (the depth).
        b: The other dimension (the width).
        shear_modulus: Shear modulus of the material.
        torsion_constant: Saint-Venant's torsion constant of the rectangle.

    Returns:
        ``(G12, G13)``.

    Raises:
        ValueError: If the torsion constant is not one a rectangle of this
            size can have (it must be positive and below a third of its
            long side times the cube of its short one).
    """
    if not (a > 0 and b > 0 and shear_modulus > 0):
        raise ValueError(
            f"rectangle needs positive sizes and shear modulus, got a={a}, "
            f"b={b}, G={shear_modulus}"
        )
    limit = max(a, b) * min(a, b) ** 3 / 3.0
    if not 0 < torsion_constant < limit:
        raise ValueError(
            f"torsion constant {torsion_constant} is not between 0 and "
            f"a third of the long side times the short one cubed, {limit}"
        )
    target = shear_modulus * torsion_constant
    modulus_12 = RECTANGLE_SHEAR_COEFFICIENT * shear_modulus
    p = modulus_12 * a * b**3 / 12.0
    if 4.0 * p > target:
        q = target * p / (4.0 * p - target)
        modulus_13 = 12.0 * q / (b * a**3)
        if modulus_13 <= shear_modulus:
            return modulus_12, modulus_13
    q = shear_modulus * b * a**3 / 12.0
    p = target * q / (4.0 * q - target)
    return 12.0 * p / (a * b**3), shear_modulus


def get_native_section(section_type: Optional[str]) -> Optional[SectionProfile]:
    """Return the SectionProfile for a B31-native section, or None.

    Returns None for GENERAL types and for unknown types.
    """
    if not section_type:
        return None
    profile = SECTION_REGISTRY.get(section_type.lower())
    if profile and not profile.use_general:
        return profile
    return None
