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
  ``SECTION=RECT``. Only the solid rectangle is written this way. CalculiX
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
c                   IfcChannelProfileDef
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
    "c": SectionProfile(True, None, None),  # IfcChannelProfileDef
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
    Shear is left to the material: the writer gives the rectangle shear
    moduli that make its shear stiffness the section's. Torsion cannot be matched; a solid rectangle is much stiffer
    in torsion than an open section.

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


def is_supported(section_type: Optional[str]) -> bool:
    """Return True if the section type is in the registry."""
    if not section_type:
        return False
    return section_type.lower() in SECTION_REGISTRY
