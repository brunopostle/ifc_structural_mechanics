"""
Test configuration for pytest.

This file is automatically loaded by pytest and contains configuration and fixtures
for the test suite.
"""

import sys
import pytest
import shutil
from pathlib import Path

# Add the src directory to the Python path so that we can import our package
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))


def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "integration: mark a test as an integration test"
    )


# Define a consistent temp directory
PERSISTENT_TEST_DIR = Path("/tmp/ifc_structural_analysis_tests")


@pytest.fixture(scope="function")
def persistent_temp_dir():
    """
    Fixture that provides a consistent temporary directory.
    The directory is cleared at the start of each test but preserved at the end.
    """
    # Create the directory if it doesn't exist
    PERSISTENT_TEST_DIR.mkdir(exist_ok=True)

    # Clear the directory contents but keep the directory itself
    for item in PERSISTENT_TEST_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    # Return the directory path for the test to use
    yield PERSISTENT_TEST_DIR

    # No cleanup code here - we want to preserve files after the test
    # Print message about where to find the artifacts
    print(f"\nTest artifacts preserved at: {PERSISTENT_TEST_DIR}")
