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
* **B31 + native keyword** (``use_general=False``): CalculiX B31 beam element
  with a specific ``SECTION=`` keyword (RECT, CIRC, PIPE, BOX).  CalculiX
  internally expands B31 to C3D8I bricks.
* **U1 + GENERAL** (``use_general=True``): CalculiX built-in Timoshenko beam
  element using ``SECTION=GENERAL`` with A, I11, I22, k_s computed from the
  domain Section's area/moment-of-inertia fields.  Used for all open and
  asymmetric profiles (I, L, T, C, etc.) where the section-level properties
  are more reliable than trying to match exact dimensional inputs.

Supported IFC profile types per domain section_type
----------------------------------------------------
rectangular      IfcRectangleProfileDef
circular         IfcCircleProfileDef (solid)
pipe             IfcCircleHollowProfileDef
hollow_circular  IfcCircleHollowProfileDef (alias, same as pipe)
box              IfcRectangleHollowProfileDef
hollow_rect      IfcRectangleHollowProfileDef (alias)
i                IfcIShapeProfileDef, IfcAsymmetricIShapeProfileDef
l                IfcLShapeProfileDef
t                IfcTShapeProfileDef
c                IfcChannelProfileDef
u                IfcUShapeProfileDef  (future)
z                IfcZShapeProfileDef  (future)
"""

from typing import Callable, Dict, NamedTuple, Optional


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
    return f"{d['width']:.6e}, {d['height']:.6e}"


def _fmt_circ(d: dict) -> str:
    return f"{d['radius']:.6e}"


def _fmt_pipe(d: dict) -> str:
    return f"{d['outer_radius']:.6e}, {d['inner_radius']:.6e}"


def _fmt_hollow_circ(d: dict) -> str:
    r_o = d["outer_radius"]
    r_i = r_o - d["thickness"]
    return f"{r_o:.6e}, {r_i:.6e}"


def _fmt_box(d: dict) -> str:
    t = d["wall_thickness"]
    # CalculiX BOX: a (local-1, height), b (local-2, width), t1 t2 t3 t4
    return (
        f"{d['height']:.6e}, {d['width']:.6e}," f" {t:.6e}, {t:.6e}, {t:.6e}, {t:.6e}"
    )


def _fmt_hollow_rect(d: dict) -> str:
    t = d["thickness"]
    return (
        f"{d['outer_height']:.6e}, {d['outer_width']:.6e},"
        f" {t:.6e}, {t:.6e}, {t:.6e}, {t:.6e}"
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Maps domain ``section_type`` strings (lower-case) to their CalculiX format.
#: This is the single source of truth consulted by the writer and by any
#: code that needs to know whether a section type is supported.
SECTION_REGISTRY: Dict[str, SectionProfile] = {
    # ---- B31 native (exact CalculiX SECTION= keyword) ----
    "rectangular": SectionProfile(False, "RECT", _fmt_rect),
    "circular": SectionProfile(False, "CIRC", _fmt_circ),
    "pipe": SectionProfile(False, "PIPE", _fmt_pipe),
    "hollow_circular": SectionProfile(False, "PIPE", _fmt_hollow_circ),
    "box": SectionProfile(False, "BOX", _fmt_box),
    "hollow_rectangular": SectionProfile(False, "BOX", _fmt_hollow_rect),
    # ---- U1 / GENERAL (computed A, Iy, Iz, ks from Section properties) ----
    # Each of these is handled by _write_beam_section_general() in the writer.
    # Add IFC extraction handlers in properties_extractor / members_extractor
    # when a new type is needed — no other code changes required.
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
