"""What CalculiX prints while it runs: whether it finished, and its warnings."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ..utils.messages import warning

logger = logging.getLogger(__name__)

# Most warnings CalculiX can repeat before they are counted and not listed
_LISTED = 10


def solver_warnings(output_text: str) -> List[Dict[str, Any]]:
    """Return the warnings CalculiX printed, each one once.

    A warning starts at a line with ``*WARNING`` and runs to the next blank
    line::

         *WARNING in calinput: no density was assigned
                  to material STEEL in a dynamic
                  calculation or ...

    CalculiX repeats a warning in every step and for every node or element
    it concerns. Warnings that differ only in their numbers are given once,
    with the first text and how often it came.

    Args:
        output_text: Everything CalculiX wrote to standard output.

    Returns:
        Warning dicts in the form used by ``result["warnings"]``.
    """
    counts: Dict[str, int] = {}
    first: Dict[str, str] = {}
    block: Optional[List[str]] = None
    for line in (output_text or "").splitlines() + [""]:
        if "*WARNING" in line:
            block = [line.split("*WARNING", 1)[1]]
        elif block is not None and line.strip():
            block.append(line)
        elif block is not None:
            text = " ".join(" ".join(block).split())
            key = re.sub(r"[-+]?\d[\d.eEdD+-]*", "#", text)
            counts[key] = counts.get(key, 0) + 1
            first.setdefault(key, text)
            block = None

    warnings = []
    for key, text in list(first.items())[:_LISTED]:
        times = f" ({counts[key]} times)" if counts[key] > 1 else ""
        warnings.append(warning("W-SLV-001", f"CalculiX{times}: *WARNING {text}"))
    if len(first) > _LISTED:
        warnings.append(
            warning(
                "W-SLV-002",
                f"CalculiX gave {len(first) - _LISTED} more kinds of warning; "
                "see its output.",
            )
        )
    if warnings:
        logger.warning(f"CalculiX printed {sum(counts.values())} warning(s)")
    return warnings


class OutputParser:
    """Reads CalculiX's output for whether the analysis finished."""

    SUCCESS_PATTERNS = [
        "Job finished",  # CalculiX 2.x actual output
        "ANALYSIS COMPLETED",
        "ANALYSIS TERMINATED SUCCESSFULLY",
        "SOLUTION CONVERGED",
        "STEP COMPLETED",
    ]

    FAILURE_PATTERNS = [
        "NO CONVERGENCE",
        "DIVERGENCE",
        "ANALYSIS INTERRUPTED",
        "ANALYSIS ABORTED",
    ]

    def check_convergence(self, output_text: str) -> Tuple[bool, Optional[str]]:
        """Check if the analysis finished.

        Args:
            output_text (str): The CalculiX output text to analyze.

        Returns:
            Tuple[bool, Optional[str]]: (converged, reason), where converged is
                True if the analysis finished, and reason says how it is known.
        """
        for pattern in self.SUCCESS_PATTERNS:
            if pattern in output_text:
                return True, "Operation completed successfully"
        for pattern in self.FAILURE_PATTERNS:
            if pattern in output_text:
                return False, f"Operation failed: {pattern} found in output"
        return False, "Unable to determine if operation completed successfully"
