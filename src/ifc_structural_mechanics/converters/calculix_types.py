"""
Stateless utility functions for converting domain entities to CalculiX formats.

This module provides pure functions for type conversions without maintaining
any state. These replace the type conversion logic previously in the mapping module.
"""

import re
from typing import Dict, List, Optional, Tuple, Pattern
from ..domain.structural_member import CurveMember, SurfaceMember, StructuralMember
from ..config.analysis_config import AnalysisConfig


# Element type mapping from Gmsh to CalculiX
GMSH_TO_CALCULIX_ELEMENTS: Dict[str, str] = {
    # Line elements (beams, trusses)
    "line": "B31",
    "line2": "B31",
    "line3": "B32",
    # Triangle elements (shells)
    "triangle": "S3",
    "triangle3": "S3",
    "triangle6": "S6",
    # Quadrilateral elements (shells)
    "quad": "S4",
    "quad4": "S4",
    "quad8": "S8",
    "quad9": "S9",
    # Tetrahedral elements (solids)
    "tetra": "C3D4",
    "tetra10": "C3D10",
    # Hexahedral elements (solids)
    "hexahedron": "C3D8",
    "hexahedron20": "C3D20",
    "hexahedron27": "C3D27",
}

# Error patterns for parsing CalculiX errors
# Format: (regex_pattern, entity_type)
CALCULIX_ERROR_PATTERNS: List[Tuple[Pattern, str]] = [
    (re.compile(r"element\s+(\d+).*negative jacobian", re.IGNORECASE), "element"),
    (re.compile(r"node\s+(\d+).*not connected", re.IGNORECASE), "node"),
    (re.compile(r"material\s+(\w+).*undefined", re.IGNORECASE), "material"),
    (re.compile(r"section\s+(\w+).*undefined", re.IGNORECASE), "section"),
    (re.compile(r"element\s+(\d+).*distorted", re.IGNORECASE), "element"),
    (re.compile(r"element\s+(\d+)", re.IGNORECASE), "element"),  # Generic element error
]


def get_calculix_element_type(
    member: StructuralMember,
    config: Optional[AnalysisConfig] = None,
    gmsh_element_type: Optional[str] = None,
) -> str:
    """
    Get the CalculiX element type for a domain member.

    Args:
        member: Domain structural member
        config: Analysis configuration (optional, for override settings)
        gmsh_element_type: Gmsh element type name (if known)

    Returns:
        CalculiX element type code (e.g., "B32", "S8")

    Examples:
        >>> member = CurveMember(...)
        >>> get_calculix_element_type(member)
        'B32'
        >>> get_calculix_element_type(member, gmsh_element_type='line3')
        'B32'
    """
    # If Gmsh element type is provided, use direct mapping
    if gmsh_element_type and gmsh_element_type in GMSH_TO_CALCULIX_ELEMENTS:
        return GMSH_TO_CALCULIX_ELEMENTS[gmsh_element_type]

    # Otherwise, determine from member type
    if isinstance(member, CurveMember):
        # Default to second-order beam elements
        return "B32"
    elif isinstance(member, SurfaceMember):
        # Default to second-order shell elements
        return "S8"
    else:
        # Fallback to generic 3D solid
        return "C3D8"


def get_element_set_name(member: StructuralMember) -> str:
    """
    Get the CalculiX element set name for a member.

    Args:
        member: Domain structural member

    Returns:
        Element set name in CalculiX format

    Examples:
        >>> member = CurveMember(id="beam_123", ...)
        >>> get_element_set_name(member)
        'ELSET_beam_123'
    """
    # Sanitize member ID for CalculiX (alphanumeric and underscore only)
    sanitized_id = re.sub(r'[^a-zA-Z0-9_]', '_', member.id)
    return f"ELSET_{sanitized_id}"


def get_node_set_name(entity_id: str) -> str:
    """
    Get the CalculiX node set name for an entity.

    Args:
        entity_id: Domain entity ID

    Returns:
        Node set name in CalculiX format

    Examples:
        >>> get_node_set_name("support_1")
        'NSET_support_1'
    """
    # Sanitize entity ID for CalculiX
    sanitized_id = re.sub(r'[^a-zA-Z0-9_]', '_', entity_id)
    return f"NSET_{sanitized_id}"


def get_material_name(material_id: str) -> str:
    """
    Get the CalculiX material name from domain material ID.

    Args:
        material_id: Domain material ID

    Returns:
        Material name in CalculiX format

    Examples:
        >>> get_material_name("steel_s355")
        'MAT_steel_s355'
    """
    # Sanitize material ID for CalculiX
    sanitized_id = re.sub(r'[^a-zA-Z0-9_]', '_', material_id)
    return f"MAT_{sanitized_id}"


def parse_calculix_error(error_line: str) -> Optional[Tuple[str, int]]:
    """
    Parse a CalculiX error message to extract entity type and ID.

    Args:
        error_line: Single line from CalculiX output

    Returns:
        Tuple of (entity_type, entity_id) if pattern matches, None otherwise

    Examples:
        >>> parse_calculix_error("*ERROR in e_c3d: element 142 has a negative jacobian")
        ('element', 142)
        >>> parse_calculix_error("*ERROR: node 57 is not connected")
        ('node', 57)
        >>> parse_calculix_error("No errors")
        None
    """
    for pattern, entity_type in CALCULIX_ERROR_PATTERNS:
        match = pattern.search(error_line)
        if match:
            try:
                entity_id = int(match.group(1))
                return (entity_type, entity_id)
            except (ValueError, IndexError):
                continue
    return None


def sanitize_calculix_name(name: str, max_length: int = 80) -> str:
    """
    Sanitize a name for use in CalculiX input files.

    CalculiX has strict naming requirements:
    - Alphanumeric and underscore only
    - Maximum length (typically 80 characters)
    - Cannot start with a number

    Args:
        name: Original name
        max_length: Maximum allowed length

    Returns:
        Sanitized name safe for CalculiX

    Examples:
        >>> sanitize_calculix_name("beam-01@floor2")
        'beam_01_floor2'
        >>> sanitize_calculix_name("123_beam")
        'N_123_beam'
    """
    # Replace invalid characters with underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)

    # Ensure doesn't start with number
    if sanitized and sanitized[0].isdigit():
        sanitized = f"N_{sanitized}"

    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    return sanitized
