"""
Base parser module for the IFC structural analysis extension.

This module provides a base parser class with common functionality for
parsing output and results from structural analysis software, specifically
focusing on pattern matching, error/warning classification, result organization,
and entity mapping.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple, Any

# Configure logging
logger = logging.getLogger(__name__)


class BaseParser:
    """
    Base parser for structural analysis output and results.

    This class provides common functionality for pattern matching, error classification,
    result organization, and entity mapping that can be used by specific parsers like
    OutputParser and ResultsParser.
    """

    def __init__(self, mapper: Optional[Any] = None):
        """
        Initialize the base parser.

        Args:
            mapper (Optional[Any]): Domain to software mapper for
                tracing data back to domain entities.
        """
        self.mapper = mapper

    def match_patterns(
        self,
        text: str,
        patterns: List[Tuple[str, Optional[str], str]],
    ) -> List[Dict[str, Any]]:
        """
        Match patterns against text and extract relevant information.

        Args:
            text (str): The text to analyze.
            patterns (List[Tuple[str, Optional[str], str]]): List of patterns to match,
                each as (regex_pattern, entity_type, severity).

        Returns:
            List[Dict[str, Any]]: List of dictionaries containing matched information.
        """
        matches = []

        # Process each line for patterns
        for line in text.splitlines():
            for pattern, entity_type, severity in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    match_info = {
                        "message": line.strip(),
                        "severity": severity,
                        "entity_type": entity_type,
                        "ccx_id": None,
                        "domain_id": None,
                    }

                    # Extract entity ID if available
                    if entity_type and match.groups():
                        try:
                            ccx_id = match.group(1)
                            # Convert to integer for node and element types
                            if entity_type in ["node", "element"]:
                                ccx_id = int(ccx_id)

                            match_info["ccx_id"] = ccx_id

                            # Map to domain entity if mapper is available
                            if self.mapper and entity_type:
                                try:
                                    domain_id = self.mapper.get_domain_entity_id(
                                        ccx_id, entity_type
                                    )
                                    match_info["domain_id"] = domain_id
                                except (KeyError, ValueError):
                                    # Entity not found in mapper
                                    pass
                        except (IndexError, ValueError):
                            # Failed to extract ID
                            pass

                    matches.append(match_info)
                    break  # Stop after finding the first matching pattern

        return matches

    def classify_severity(
        self, text: str, error_patterns: List, warning_patterns: List
    ) -> str:
        """
        Classify the severity of a message based on pattern matching.

        Args:
            text (str): The message to classify.
            error_patterns (List): Patterns that indicate errors.
            warning_patterns (List): Patterns that indicate warnings.

        Returns:
            str: Severity level ('critical', 'error', or 'warning').
        """
        # Check if it matches any critical error pattern
        for pattern, _, _ in error_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return "critical"

        # Check if it matches any warning pattern
        for pattern, _, _ in warning_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return "warning"

        # Default classification based on keywords
        if re.search(r"(?i)fatal|error|failed|negative|zero", text):
            return "critical"
        elif re.search(r"(?i)warning|caution|note", text):
            return "warning"

        # Default to error level if unclear
        return "error"

    def map_to_entity(self, text: str, patterns: List) -> Dict[str, Any]:
        """
        Map a message to an entity in the domain model.

        Args:
            text (str): The message to map.
            patterns (List): Patterns that extract entity information.

        Returns:
            Dict[str, Any]: Mapping information including entity_type, ccx_id, and domain_id.
        """
        if not self.mapper:
            return {"entity_type": None, "ccx_id": None, "domain_id": None}

        # Check each pattern for entity references
        for pattern, entity_type, _ in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match and entity_type and match.groups():
                try:
                    ccx_id = match.group(1)
                    # Convert to integer for node and element types
                    if entity_type in ["node", "element"]:
                        ccx_id = int(ccx_id)

                    # Try to map to domain entity
                    try:
                        domain_id = self.mapper.get_domain_entity_id(
                            ccx_id, entity_type
                        )
                        return {
                            "entity_type": entity_type,
                            "ccx_id": ccx_id,
                            "domain_id": domain_id,
                        }
                    except (KeyError, ValueError):
                        # Entity not found in mapper
                        return {
                            "entity_type": entity_type,
                            "ccx_id": ccx_id,
                            "domain_id": None,
                        }
                except (IndexError, ValueError):
                    # Failed to extract ID
                    pass

        # No entity reference found
        return {"entity_type": None, "ccx_id": None, "domain_id": None}

    def generate_summary(self, parse_result: Dict[str, List[Dict[str, Any]]]) -> str:
        """
        Generate a human-readable summary of results.

        Args:
            parse_result (Dict[str, List[Dict[str, Any]]]): The result from parsing.

        Returns:
            str: A human-readable summary.
        """
        errors = parse_result.get("errors", [])
        warnings = parse_result.get("warnings", [])

        summary = []

        if errors:
            summary.append(f"Found {len(errors)} critical issues:")
            for i, error in enumerate(errors, 1):
                entity_info = ""
                if error.get("entity_type") and error.get("ccx_id"):
                    entity_info = f" in {error['entity_type']} {error['ccx_id']}"
                    if error.get("domain_id"):
                        entity_info += f" (domain ID: {error['domain_id']})"

                summary.append(f"  {i}. {error['message']}{entity_info}")

        if warnings:
            summary.append(f"\nFound {len(warnings)} warnings:")
            for i, warning in enumerate(warnings, 1):
                entity_info = ""
                if warning.get("entity_type") and warning.get("ccx_id"):
                    entity_info = f" in {warning['entity_type']} {warning['ccx_id']}"
                    if warning.get("domain_id"):
                        entity_info += f" (domain ID: {warning['domain_id']})"

                summary.append(f"  {i}. {warning['message']}{entity_info}")

        if not errors and not warnings:
            summary.append("No errors or warnings detected in the analysis output.")

        return "\n".join(summary)

    def check_completion_status(
        self, output_text: str, success_patterns: List[str], failure_patterns: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if an operation completed successfully based on output patterns.

        Args:
            output_text (str): The output text to analyze.
            success_patterns (List[str]): Patterns indicating successful completion.
            failure_patterns (List[str]): Patterns indicating failure.

        Returns:
            Tuple[bool, Optional[str]]: (completed, reason), where completed is True if
                the operation completed successfully, and reason is a message explaining the result.
        """
        # Check for success indicators
        for pattern in success_patterns:
            if pattern in output_text:
                return True, "Operation completed successfully"

        # Check for failure indicators
        for pattern in failure_patterns:
            if pattern in output_text:
                return False, f"Operation failed: {pattern} found in output"

        # Inconclusive
        return False, "Unable to determine if operation completed successfully"

    def set_mapper(self, mapper: Any) -> None:
        """
        Set the domain to software mapper.

        Args:
            mapper (Any): The mapper to use for entity handling.
        """
        self.mapper = mapper

    def parse_file_content(self, file_path: str) -> str:
        """
        Read and return file content with proper error handling.

        Args:
            file_path (str): Path to the file to read.

        Returns:
            str: The content of the file.

        Raises:
            FileNotFoundError: If the file is not found.
            IOError: If the file cannot be read.
        """
        try:
            with open(file_path, "r") as f:
                content = f.read()
                logger.debug(f"Read {len(content)} bytes from {file_path}")
                return content
        except FileNotFoundError:
            logger.warning(f"File not found: {file_path}")
            raise FileNotFoundError(f"File not found: {file_path}")
        except IOError as e:
            logger.error(f"Error reading file {file_path}: {str(e)}")
            raise IOError(f"Error reading file {file_path}: {str(e)}")
