"""
CalculiX output parser module for the IFC structural analysis extension.

This module provides functionality to parse and analyze CalculiX output,
identify errors and warnings, classify their severity, and map them back
to the original IFC entities.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple, Any

from .base_parser import BaseParser
from ..mapping.domain_to_calculix import DomainToCalculixMapper

# Configure logging
logger = logging.getLogger(__name__)


class OutputParser(BaseParser):
    """
    Parser for CalculiX output.

    This class analyzes CalculiX output text to identify errors and warnings,
    classify their severity, and map them back to the original IFC entities.
    """

    # Define error patterns with regular expressions
    ERROR_PATTERNS = [
        # Negative jacobian errors (critical)
        (r"(?i).*negative jacobian.*element\s+(\d+)", "element", "critical"),
        (r"(?i).*zero jacobian.*element\s+(\d+)", "element", "critical"),
        # Material errors
        (r"(?i).*material\s+[\"']?(\w+)[\"']?\s+.*undefined", "material", "critical"),
        (r"(?i).*material\s+[\"']?(\w+)[\"']?\s+.*nonexistent", "material", "critical"),
        (r"(?i).*material\s+property.*missing", None, "critical"),
        # Node/element errors
        (r"(?i).*node\s+(\d+).*not connected", "node", "critical"),
        (r"(?i).*node\s+(\d+).*nonexistent", "node", "critical"),
        (r"(?i).*element\s+(\d+).*nonexistent", "element", "critical"),
        # Section errors
        (r"(?i).*section\s+(\w+).*undefined", "section", "critical"),
        (r"(?i).*section\s+(\w+).*nonexistent", "section", "critical"),
        # Convergence errors
        (r"(?i).*no convergence.*", None, "critical"),
        (r"(?i).*divergence.*step\s+(\d+)", None, "critical"),
        (r"(?i).*solver\s+failed\s+to\s+converge", None, "critical"),
        # Stiffness/matrix errors
        (r"(?i).*zero\s+pivot.*", None, "critical"),
        (r"(?i).*singular\s+matrix.*", None, "critical"),
        (r"(?i).*ill-conditioned\s+system.*", None, "critical"),
        # General errors
        (r"(?i).*error\s+in\s+step\s+(\d+)", None, "critical"),
        (r"(?i).*fatal\s+error.*", None, "critical"),
        (r"(?i)^error:.*", None, "critical"),
        (r"(?i).*analysis\s+failed.*", None, "critical"),
    ]

    # Define warning patterns with regular expressions
    WARNING_PATTERNS = [
        # General warnings
        (r"(?i)^warning:.*", None, "warning"),
        (r"(?i).*warnung:.*", None, "warning"),
        # Specific warnings
        (r"(?i).*large\s+displacement.*element\s+(\d+)", "element", "warning"),
        (r"(?i).*small\s+pivot.*", None, "warning"),
        (r"(?i).*distorted\s+element.*(\d+)", "element", "warning"),
        (r"(?i).*high\s+aspect\s+ratio.*element\s+(\d+)", "element", "warning"),
        (r"(?i).*unreasonable\s+deformation.*element\s+(\d+)", "element", "warning"),
        # Convergence warnings
        (r"(?i).*slow\s+convergence.*", None, "warning"),
        (r"(?i).*convergence\s+problems.*", None, "warning"),
        # Analysis warnings
        (r"(?i).*not\s+recommended.*", None, "warning"),
        (r"(?i).*user\s+caution.*", None, "warning"),
    ]

    # Define success and failure patterns for CalculiX output
    SUCCESS_PATTERNS = [
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

    def __init__(self, mapper: Optional[DomainToCalculixMapper] = None):
        """
        Initialize the output parser.

        Args:
            mapper (Optional[DomainToCalculixMapper]): Domain to CalculiX mapper for
                tracing errors back to IFC entities.
        """
        super().__init__(mapper)

    def parse_output(self, output_text: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Parse CalculiX output text to identify errors and warnings.

        Args:
            output_text (str): The CalculiX output text to parse.

        Returns:
            Dict[str, List[Dict[str, Any]]]: Dictionary with 'errors' and 'warnings' lists,
                each containing dictionaries with message, severity, entity_type,
                ccx_id, and domain_id details.
        """
        if not output_text:
            return {"errors": [], "warnings": []}

        # Detect errors and warnings using base class methods
        errors = self.match_patterns(output_text, self.ERROR_PATTERNS)
        warnings = self.match_patterns(output_text, self.WARNING_PATTERNS)

        # Check for completion status
        completed, reason = self.check_completion_status(
            output_text, self.SUCCESS_PATTERNS, self.FAILURE_PATTERNS
        )

        # Add analysis completion status error if necessary
        if (
            not completed
            and "ANALYSIS INTERRUPTED" in output_text
            or "ANALYSIS ABORTED" in output_text
        ):
            errors.append(
                {
                    "message": "Analysis was interrupted or aborted before completion",
                    "severity": "critical",
                    "entity_type": None,
                    "ccx_id": None,
                    "domain_id": None,
                }
            )

        # Log summary of findings
        if errors:
            logger.error(f"Found {len(errors)} errors in CalculiX output")
        if warnings:
            logger.warning(f"Found {len(warnings)} warnings in CalculiX output")

        return {"errors": errors, "warnings": warnings}

    def classify_error_severity(self, error_text: str) -> str:
        """
        Classify the severity of an error message.

        Args:
            error_text (str): The error message to classify.

        Returns:
            str: Severity level ('critical', 'error', or 'warning').
        """
        return self.classify_severity(
            error_text, self.ERROR_PATTERNS, self.WARNING_PATTERNS
        )

    def map_error_to_entity(self, error_text: str) -> Dict[str, Any]:
        """
        Map an error message to an original entity in the domain model.

        Args:
            error_text (str): The error message to map.

        Returns:
            Dict[str, Any]: Mapping information including entity_type, ccx_id, and domain_id.
        """
        return self.map_to_entity(error_text, self.ERROR_PATTERNS)

    def check_convergence(self, output_text: str) -> Tuple[bool, Optional[str]]:
        """
        Check if the analysis converged successfully.

        Args:
            output_text (str): The CalculiX output text to analyze.

        Returns:
            Tuple[bool, Optional[str]]: (converged, reason), where converged is True if
                the analysis converged, and reason is a message explaining the result.
        """
        return self.check_completion_status(
            output_text, self.SUCCESS_PATTERNS, self.FAILURE_PATTERNS
        )

    def generate_error_summary(
        self, parse_result: Dict[str, List[Dict[str, Any]]]
    ) -> str:
        """
        Generate a human-readable summary of errors and warnings.

        Args:
            parse_result (Dict[str, List[Dict[str, Any]]]): The result from parse_output.

        Returns:
            str: A human-readable summary of errors and warnings.
        """
        return self.generate_summary(parse_result)
