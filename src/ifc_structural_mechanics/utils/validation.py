"""
Validation utilities for structural analysis.

This module provides functions for validating analysis results and checking
equilibrium conditions.
"""

import logging
from typing import Dict, Tuple

import numpy as np

from ..domain.result import ReactionForceResult
from ..domain.structural_model import StructuralModel

logger = logging.getLogger(__name__)


def sum_input_loads(model: StructuralModel) -> np.ndarray:
    """
    Sum all input loads by component (X, Y, Z).

    This function iterates through all load groups in the model and sums
    the force components of all loads.

    Args:
        model: The structural model containing load groups

    Returns:
        numpy array with total forces [Fx_total, Fy_total, Fz_total]
    """
    total_forces = np.array([0.0, 0.0, 0.0])

    for load_group in model.load_groups:
        for load in load_group.loads:
            try:
                force_vector = load.get_force_vector()
                # Ensure the force vector is 3D
                if len(force_vector) == 2:
                    force_vector = np.array([force_vector[0], force_vector[1], 0.0])
                elif len(force_vector) != 3:
                    logger.warning(
                        f"Load {load.id} has invalid force vector length: {len(force_vector)}"
                    )
                    continue

                total_forces += force_vector
            except Exception as e:
                logger.warning(f"Error processing load {load.id}: {str(e)}")
                continue

    return total_forces


def sum_reaction_forces(model: StructuralModel) -> np.ndarray:
    """
    Sum all reaction forces by component (X, Y, Z).

    This function iterates through all results in the model and sums
    the reaction force components.

    Args:
        model: The structural model containing results

    Returns:
        numpy array with total reaction forces [Rx_total, Ry_total, Rz_total]
    """
    total_reactions = np.array([0.0, 0.0, 0.0])

    for result in model.results:
        if isinstance(result, ReactionForceResult):
            try:
                forces = result.get_forces()
                total_reactions += np.array(forces)
            except Exception as e:
                logger.warning(
                    f"Error processing reaction at {result.reference_element}: {str(e)}"
                )
                continue

    return total_reactions


def check_equilibrium(
    model: StructuralModel, tolerance: float = 1e-6, relative_tolerance: float = 1e-3
) -> Tuple[bool, Dict[str, any]]:
    """
    Check if the analysis satisfies force equilibrium.

    This function verifies that the sum of all input loads equals the sum
    of all reaction forces (Newton's third law). This is a fundamental
    validation check for structural analysis convergence.

    The check uses both absolute and relative tolerances:
    - Absolute tolerance: Used when forces are very small
    - Relative tolerance: Used when forces are larger (as percentage of max force)

    Args:
        model: The structural model with loads and results
        tolerance: Absolute tolerance for equilibrium check (default: 1e-6)
        relative_tolerance: Relative tolerance as fraction of max force (default: 1e-3 = 0.1%)

    Returns:
        Tuple of (equilibrium_satisfied, details_dict)
        - equilibrium_satisfied: True if equilibrium is satisfied within tolerance
        - details_dict: Dictionary containing:
            - 'input_loads': Total input loads [Fx, Fy, Fz]
            - 'reaction_forces': Total reaction forces [Rx, Ry, Rz]
            - 'difference': Difference between loads and reactions [dFx, dFy, dFz]
            - 'max_difference': Maximum absolute component difference
            - 'max_force': Maximum force magnitude for relative tolerance
            - 'tolerance_used': The tolerance value used for comparison
            - 'equilibrium_satisfied': Boolean result
    """
    # Sum input loads
    input_loads = sum_input_loads(model)

    # Sum reaction forces
    reaction_forces = sum_reaction_forces(model)

    # Calculate difference (should be close to zero for equilibrium)
    # Note: Reactions oppose loads, so we expect: loads + reactions ≈ 0
    difference = input_loads + reaction_forces

    # Calculate component-wise absolute differences
    abs_difference = np.abs(difference)
    max_difference = np.max(abs_difference)

    # Determine appropriate tolerance
    max_force = max(np.max(np.abs(input_loads)), np.max(np.abs(reaction_forces)))

    # Use relative tolerance if forces are large, absolute tolerance if small
    if max_force > tolerance / relative_tolerance:
        tolerance_used = max_force * relative_tolerance
    else:
        tolerance_used = tolerance

    # Check equilibrium
    equilibrium_satisfied = max_difference <= tolerance_used

    # Prepare detailed results
    details = {
        "input_loads": input_loads.tolist(),
        "reaction_forces": reaction_forces.tolist(),
        "difference": difference.tolist(),
        "max_difference": float(max_difference),
        "max_force": float(max_force),
        "tolerance_used": float(tolerance_used),
        "equilibrium_satisfied": equilibrium_satisfied,
    }

    # Log results
    if equilibrium_satisfied:
        logger.info(
            f"Equilibrium check PASSED: max difference = {max_difference:.3e}, "
            f"tolerance = {tolerance_used:.3e}"
        )
    else:
        logger.warning(
            f"Equilibrium check FAILED: max difference = {max_difference:.3e}, "
            f"tolerance = {tolerance_used:.3e}"
        )
        logger.warning(
            f"  Input loads:      [{input_loads[0]:.3e}, {input_loads[1]:.3e}, {input_loads[2]:.3e}]"
        )
        logger.warning(
            f"  Reaction forces:  [{reaction_forces[0]:.3e}, {reaction_forces[1]:.3e}, {reaction_forces[2]:.3e}]"
        )
        logger.warning(
            f"  Difference:       [{difference[0]:.3e}, {difference[1]:.3e}, {difference[2]:.3e}]"
        )

    return equilibrium_satisfied, details


def format_equilibrium_report(details: Dict[str, any]) -> str:
    """
    Format equilibrium check results as a human-readable report.

    Args:
        details: Details dictionary returned by check_equilibrium()

    Returns:
        Formatted string report
    """
    input_loads = details["input_loads"]
    reaction_forces = details["reaction_forces"]
    difference = details["difference"]

    report = []
    report.append("=" * 60)
    report.append("EQUILIBRIUM CHECK REPORT")
    report.append("=" * 60)
    report.append("")
    report.append("Input Loads (X, Y, Z):")
    report.append(
        f"  [{input_loads[0]:>12.4e}, {input_loads[1]:>12.4e}, {input_loads[2]:>12.4e}]"
    )
    report.append("")
    report.append("Reaction Forces (X, Y, Z):")
    report.append(
        f"  [{reaction_forces[0]:>12.4e}, {reaction_forces[1]:>12.4e}, {reaction_forces[2]:>12.4e}]"
    )
    report.append("")
    report.append("Difference (X, Y, Z):")
    report.append(
        f"  [{difference[0]:>12.4e}, {difference[1]:>12.4e}, {difference[2]:>12.4e}]"
    )
    report.append("")
    report.append(f"Maximum Difference:  {details['max_difference']:.4e}")
    report.append(f"Tolerance Used:      {details['tolerance_used']:.4e}")
    report.append("")

    if details["equilibrium_satisfied"]:
        report.append("Result: PASSED ✓")
    else:
        report.append("Result: FAILED ✗")

    report.append("=" * 60)

    return "\n".join(report)
