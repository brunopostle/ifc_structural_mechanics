"""
Unit conversion utilities for the IFC structural analysis extension.

This module provides utility functions for handling unit conversions between
IFC project units and SI units throughout the library.
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Union, Tuple, Any

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


def convert_point_list(
    points: List[List[float]], unit_scale: float
) -> List[List[float]]:
    """
    Convert a list of points from project units to SI units.

    Args:
        points: List of points in project units
        unit_scale: Scale factor to convert to SI units

    Returns:
        List of points in SI units
    """
    return [[c * unit_scale for c in point] for point in points]


def convert_force(
    value: Union[float, List[float]], force_scale: float
) -> Union[float, List[float]]:
    """
    Convert a force value or list of force values from project units to SI units (Newtons).

    Args:
        value: Force value or list of force values in project units
        force_scale: Scale factor to convert to SI units

    Returns:
        The converted value(s) in SI units
    """
    if isinstance(value, list):
        return [v * force_scale for v in value]
    elif isinstance(value, np.ndarray):
        return value * force_scale
    else:
        return value * force_scale


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


def convert_volume(value: float, unit_scale: float) -> float:
    """
    Convert a volume from project units to SI units (cubic meters).

    Args:
        value: Volume in project units
        unit_scale: Length scale factor to convert to SI units

    Returns:
        Volume in cubic meters
    """
    return value * (unit_scale**3)


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


def convert_elastic_modulus(
    value: float, force_scale: float, unit_scale: float
) -> float:
    """
    Convert an elastic modulus from project units to SI units (Pa = N/m^2).

    Args:
        value: Elastic modulus in project units
        force_scale: Force scale factor to convert to SI units
        unit_scale: Length scale factor to convert to SI units

    Returns:
        Elastic modulus in Pa
    """
    return value * (force_scale / (unit_scale**2))


def convert_linear_stiffness(
    value: float, force_scale: float, unit_scale: float
) -> float:
    """
    Convert a linear stiffness from project units to SI units (N/m).

    Args:
        value: Linear stiffness in project units
        force_scale: Force scale factor to convert to SI units
        unit_scale: Length scale factor to convert to SI units

    Returns:
        Linear stiffness in N/m
    """
    return value * (force_scale / unit_scale)


def convert_rotational_stiffness(
    value: float, force_scale: float, unit_scale: float
) -> float:
    """
    Convert a rotational stiffness from project units to SI units (N·m/rad).

    Args:
        value: Rotational stiffness in project units
        force_scale: Force scale factor to convert to SI units
        unit_scale: Length scale factor to convert to SI units

    Returns:
        Rotational stiffness in N·m/rad
    """
    return value * (force_scale * unit_scale)


def convert_moment(value: float, force_scale: float, unit_scale: float) -> float:
    """
    Convert a moment from project units to SI units (N·m).

    Args:
        value: Moment in project units
        force_scale: Force scale factor to convert to SI units
        unit_scale: Length scale factor to convert to SI units

    Returns:
        Moment in N·m
    """
    return value * (force_scale * unit_scale)
