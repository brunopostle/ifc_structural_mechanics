"""
Unit conversion utilities for the IFC structural analysis extension.

This module provides utility functions for handling unit conversions between
IFC project units and SI units throughout the library.
"""

import logging
from typing import List, Optional, Union

import ifcopenshell.util.unit

logger = logging.getLogger(__name__)


def convert_length(
    value: Union[float, List[float]], unit_scale: float
) -> Union[float, List[float]]:
    """
    Convert a length value or list of length values from project units to SI units.

    Args:
        value: Length value or list of length values in project units
        unit_scale: Scale factor to convert to SI units

    Returns:
        The converted value(s) in SI units
    """
    if isinstance(value, list):
        return [v * unit_scale for v in value]
    else:
        return value * unit_scale


def convert_coordinates(coords: List[float], unit_scale: float) -> List[float]:
    """
    Convert coordinate values from project units to SI units.

    Args:
        coords: Coordinates in project units
        unit_scale: Scale factor to convert to SI units

    Returns:
        Coordinates in SI units
    """
    return [c * unit_scale for c in coords]


def convert_area(value: float, unit_scale: float) -> float:
    """
    Convert an area from project units to SI units (square meters).

    Args:
        value: Area in project units
        unit_scale: Length scale factor to convert to SI units

    Returns:
        Area in square meters
    """
    return value * (unit_scale**2)


def convert_moment_of_inertia(value: float, unit_scale: float) -> float:
    """
    Convert a moment of inertia from project units to SI units (m^4).

    Args:
        value: Moment of inertia in project units
        unit_scale: Length scale factor to convert to SI units

    Returns:
        Moment of inertia in m^4
    """
    return value * (unit_scale**4)


def convert_density(
    value: float, unit_scale: float, mass_scale: Optional[float] = None
) -> float:
    """
    Convert a density from project units to SI units (kg/m^3).

    Args:
        value: Density in project units
        unit_scale: Length scale factor to convert to SI units
        mass_scale: Optional mass scale factor if different from 1.0

    Returns:
        Density in kg/m^3
    """
    mass_factor = mass_scale if mass_scale is not None else 1.0
    return value * (mass_factor / (unit_scale**3))


def unit_to_si(unit) -> float:
    """
    Scale factor from an IFC unit to SI, with mass in kilograms.

    Works through the entities of the unit, so that a gram-based unit is scaled
    to kilograms wherever it appears (IfcOpenShell's scales are to grams, which
    makes a pound 453.6) and a derived unit is scaled in any IfcOpenShell.

    Args:
        unit: An IfcSIUnit, IfcConversionBasedUnit or IfcDerivedUnit

    Returns:
        What to multiply a value in this unit by to have it in SI
    """
    if unit.is_a("IfcDerivedUnit"):
        scale = 1.0
        for element in unit.Elements:
            scale *= unit_to_si(element.Unit) ** element.Exponent
        return scale
    if unit.is_a("IfcConversionBasedUnit"):
        factor = unit.ConversionFactor
        return float(factor.ValueComponent.wrappedValue) * unit_to_si(
            factor.UnitComponent
        )
    scale = (
        ifcopenshell.util.unit.get_prefix_multiplier(unit.Prefix)
        if unit.Prefix
        else 1.0
    )
    if unit.Name == "GRAM":
        return scale * 0.001
    return scale ** {"SQUARE_METRE": 2, "CUBIC_METRE": 3}.get(unit.Name, 1)
