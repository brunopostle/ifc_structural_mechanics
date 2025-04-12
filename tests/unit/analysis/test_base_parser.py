"""
Unit tests for the BaseParser class.

This module contains tests to verify the functionality of the BaseParser class,
which provides common parsing functionality for output and result files.
"""

import os
import unittest
from unittest.mock import patch, MagicMock, mock_open

from ifc_structural_mechanics.analysis.base_parser import BaseParser


class TestBaseParser(unittest.TestCase):
    """Test cases for the BaseParser class."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = BaseParser()

        # Define test patterns for pattern matching
        self.error_patterns = [
            (r"(?i).*error.*in\s+(\w+)", "entity", "critical"),
            (r"(?i).*warning.*value\s+(\d+)", "value", "warning"),
            (r"(?i).*failed.*", None, "error"),
        ]

        self.warning_patterns = [
            (r"(?i).*caution.*element\s+(\d+)", "element", "warning"),
            (r"(?i).*note.*", None, "info"),
        ]

        # Create mock mapper for entity mapping tests
        self.mock_mapper = MagicMock()
        self.mock_mapper.get_domain_entity_id = MagicMock(return_value="domain123")
        self.parser_with_mapper = BaseParser(mapper=self.mock_mapper)

    def test_match_patterns(self):
        """Test the pattern matching functionality."""
        test_text = """
        Error in beam123: negative value
        Warning: value 456 is too high
        Operation failed due to convergence issues
        Caution: element 789 has high aspect ratio
        Note: analysis completed with minor issues
        """

        matches = self.parser.match_patterns(test_text, self.error_patterns)

        # Should find 3 matches from error_patterns
        self.assertEqual(len(matches), 3)

        # Check first match details
        self.assertIn("Error in beam123", matches[0]["message"])
        self.assertEqual(matches[0]["severity"], "critical")
        self.assertEqual(matches[0]["entity_type"], "entity")
        self.assertEqual(matches[0]["ccx_id"], "beam123")

        # Check second match
        self.assertIn("Warning: value 456", matches[1]["message"])
        self.assertEqual(matches[1]["severity"], "warning")
        self.assertEqual(matches[1]["entity_type"], "value")
        self.assertEqual(matches[1]["ccx_id"], "456")

        # Check third match
        self.assertIn("Operation failed", matches[2]["message"])
        self.assertEqual(matches[2]["severity"], "error")
        self.assertIsNone(matches[2]["entity_type"])
        self.assertIsNone(matches[2]["ccx_id"])

    def test_match_patterns_with_mapper(self):
        """Test pattern matching with entity mapping."""
        test_text = "Warning: value 456 is too high"

        matches = self.parser_with_mapper.match_patterns(test_text, self.error_patterns)

        # Check that domain mapping was attempted
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ccx_id"], "456")
        self.assertEqual(matches[0]["domain_id"], "domain123")
        self.mock_mapper.get_domain_entity_id.assert_called_once_with("456", "value")

    def test_classify_severity(self):
        """Test the severity classification functionality."""
        # Test explicit patterns
        self.assertEqual(
            self.parser.classify_severity(
                "Error in beam: critical issue",
                self.error_patterns,
                self.warning_patterns,
            ),
            "critical",
        )

        self.assertEqual(
            self.parser.classify_severity(
                "Caution: element 123 has high ratio",
                self.error_patterns,
                self.warning_patterns,
            ),
            "warning",
        )

        # Test keyword-based classification
        self.assertEqual(
            self.parser.classify_severity(
                "Fatal: system crash", self.error_patterns, self.warning_patterns
            ),
            "critical",
        )

        self.assertEqual(
            self.parser.classify_severity(
                "Just a note of caution", self.error_patterns, self.warning_patterns
            ),
            "warning",
        )

        # Test default classification
        self.assertEqual(
            self.parser.classify_severity(
                "Some unclassified message", self.error_patterns, self.warning_patterns
            ),
            "error",
        )

    def test_map_to_entity(self):
        """Test the entity mapping functionality."""
        # Test with pattern that extracts entity information
        entity_info = self.parser_with_mapper.map_to_entity(
            "Error in beam123: critical issue", self.error_patterns
        )

        self.assertEqual(entity_info["entity_type"], "entity")
        self.assertEqual(entity_info["ccx_id"], "beam123")
        self.assertEqual(entity_info["domain_id"], "domain123")

        # Test with pattern that doesn't match
        entity_info = self.parser_with_mapper.map_to_entity(
            "Some text with no entity information", self.error_patterns
        )

        self.assertIsNone(entity_info["entity_type"])
        self.assertIsNone(entity_info["ccx_id"])
        self.assertIsNone(entity_info["domain_id"])

        # Test without a mapper
        entity_info = self.parser.map_to_entity(
            "Error in beam123: critical issue", self.error_patterns
        )

        self.assertIsNone(entity_info["domain_id"])

    def test_generate_summary(self):
        """Test the summary generation functionality."""
        parse_result = {
            "errors": [
                {
                    "message": "Error in beam123: critical issue",
                    "severity": "critical",
                    "entity_type": "entity",
                    "ccx_id": "beam123",
                    "domain_id": "domain123",
                }
            ],
            "warnings": [
                {
                    "message": "Warning: value 456 is too high",
                    "severity": "warning",
                    "entity_type": "value",
                    "ccx_id": "456",
                    "domain_id": None,
                }
            ],
        }

        summary = self.parser.generate_summary(parse_result)

        # Check that summary contains both error and warning information
        self.assertIn("Found 1 critical issues", summary)
        self.assertIn("Error in beam123", summary)
        self.assertIn("domain ID: domain123", summary)
        self.assertIn("Found 1 warnings", summary)
        self.assertIn("Warning: value 456", summary)

        # Test with empty result
        empty_summary = self.parser.generate_summary({})
        self.assertIn("No errors or warnings detected", empty_summary)

    def test_check_completion_status(self):
        """Test the completion status checking functionality."""
        success_patterns = ["SUCCESS", "COMPLETED"]
        failure_patterns = ["FAILED", "ERROR"]

        # Test successful completion
        completed, reason = self.parser.check_completion_status(
            "Operation COMPLETED successfully", success_patterns, failure_patterns
        )

        self.assertTrue(completed)
        self.assertIn("completed successfully", reason)

        # Test failure
        completed, reason = self.parser.check_completion_status(
            "Operation FAILED due to errors", success_patterns, failure_patterns
        )

        self.assertFalse(completed)
        self.assertIn("failed", reason.lower())

        # Test inconclusive
        completed, reason = self.parser.check_completion_status(
            "Operation finished with unknown status", success_patterns, failure_patterns
        )

        self.assertFalse(completed)
        self.assertIn("unable to determine", reason.lower())

    def test_set_mapper(self):
        """Test setting a mapper after initialization."""
        parser = BaseParser()
        self.assertIsNone(parser.mapper)

        new_mapper = MagicMock()
        parser.set_mapper(new_mapper)
        self.assertEqual(parser.mapper, new_mapper)

    @patch("builtins.open", new_callable=mock_open, read_data="Test file content")
    def test_parse_file_content(self, mock_file):
        """Test the file content parsing functionality."""
        # Test successful file reading
        content = self.parser.parse_file_content("test_file.txt")
        self.assertEqual(content, "Test file content")
        mock_file.assert_called_once_with("test_file.txt", "r")

        # Test file not found error
        mock_file.side_effect = FileNotFoundError("File not found")
        with self.assertRaises(FileNotFoundError):
            self.parser.parse_file_content("missing_file.txt")

        # Test IO error
        mock_file.side_effect = IOError("IO Error")
        with self.assertRaises(IOError):
            self.parser.parse_file_content("error_file.txt")


if __name__ == "__main__":
    unittest.main()
