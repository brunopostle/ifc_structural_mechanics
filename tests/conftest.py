"""
Test configuration for pytest.

This file is automatically loaded by pytest and contains configuration and fixtures
for the test suite.
"""

import shutil
import sys
from pathlib import Path

import pytest

# Add the src directory to the Python path so that we can import our package
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))


def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "integration: mark a test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )


BUILDING_02_IFC = (
    Path(__file__).parent.parent
    / "examples"
    / "analysis-models"
    / "ifcFiles"
    / "building_02.ifc"
)


@pytest.fixture(scope="session")
def building_02_run(tmp_path_factory):
    """Run building_02 through the full pipeline once for the whole session.

    The run takes over a minute, so every slow test shares it. Returns
    ``(result, output_dir)`` from ``analyze_ifc`` with a 2 m mesh and gravity.
    """
    if not BUILDING_02_IFC.exists():
        pytest.skip(f"IFC file not found: {BUILDING_02_IFC}")
    if shutil.which("ccx") is None:
        pytest.skip("CalculiX (ccx) not installed")

    from ifc_structural_mechanics.api.structural_analysis import analyze_ifc

    output_dir = str(tmp_path_factory.mktemp("building_02"))
    result = analyze_ifc(
        ifc_path=str(BUILDING_02_IFC),
        output_dir=output_dir,
        mesh_size=2.0,
        gravity=True,
    )
    return result, output_dir


@pytest.fixture(scope="session")
def building_02_model():
    """Domain model extracted from building_02, shared across the session."""
    if not BUILDING_02_IFC.exists():
        pytest.skip(f"IFC file not found: {BUILDING_02_IFC}")

    from ifc_structural_mechanics.ifc.extractor import Extractor

    return Extractor(str(BUILDING_02_IFC)).extract_model()


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
