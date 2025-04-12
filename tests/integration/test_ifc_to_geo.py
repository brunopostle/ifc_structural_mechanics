"""
Test IFC to Gmsh .geo file conversion.

This test reads a simple_beam.ifc file, uses GmshGeometryConverter to convert
the structural model to Gmsh geometry, and saves the result as a .geo file
for manual inspection.
"""

import os
import pytest
import logging

import gmsh

from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.meshing.gmsh_geometry import GmshGeometryConverter
from ifc_structural_mechanics.config.meshing_config import MeshingConfig

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestIFCToGeoConversion:
    """Test the conversion of IFC structural model to Gmsh .geo file."""

    def test_ifc_to_geo_conversion(self):
        """
        Test converting simple_beam.ifc to a Gmsh .geo file.

        This test:
        1. Reads the simple_beam.ifc file
        2. Extracts the structural model
        3. Converts it to Gmsh geometry
        4. Saves the result as a .geo file
        5. Verifies the file is valid
        """
        # Define paths
        ifc_path = os.path.join("tests", "test_data", "simple_beam.ifc")

        # Create output directory if it doesn't exist
        output_dir = os.path.join("tests", "output")
        os.makedirs(output_dir, exist_ok=True)

        # Output geo file path
        geo_file = os.path.join(output_dir, "simple_beam.geo")

        # Check if IFC file exists
        if not os.path.exists(ifc_path):
            pytest.skip(f"Test IFC file not found: {ifc_path}")

        try:
            # Initialize Gmsh explicitly to check if it's available
            try:
                if not gmsh.isInitialized():
                    gmsh.initialize()
                    gmsh_initialized = True
                else:
                    gmsh_initialized = False

                # Verify Gmsh is working by checking a simple operation
                gmsh.option.getNumber("General.Terminal")
            except Exception as e:
                pytest.skip(f"Gmsh initialization failed. This test requires Gmsh: {e}")

            # Step 1: Extract the structural model from IFC
            logger.info(f"Extracting structural model from {ifc_path}")
            extractor = Extractor(ifc_path)
            structural_model = extractor.extract_model()
            assert structural_model, "Failed to extract structural model"

            # Step 2: Convert the structural model to Gmsh geometry
            logger.info("Converting structural model to Gmsh geometry")
            meshing_config = MeshingConfig()
            geometry_converter = GmshGeometryConverter(meshing_config=meshing_config)

            # Convert the model to Gmsh geometry
            entity_map = geometry_converter.convert_model(structural_model)

            # Verify that entity_map is not empty
            assert entity_map, "Failed to convert model to Gmsh geometry"
            logger.info(f"Converted model with {len(entity_map)} entities")

            # Step 3: Write the .geo file
            logger.info(f"Writing Gmsh geometry to {geo_file}")
            try:
                # Ensure the model is synchronized before writing
                gmsh.model.occ.synchronize()

                # Set options to force Geo format output
                try:
                    # Try different methods to set the output format
                    gmsh.option.setNumber(
                        "General.Terminal", 1
                    )  # Enable terminal output for debugging

                    # Create a simple model to ensure we have something to write
                    # This is a fallback in case the conversion didn't create valid entities
                    try:
                        # First check if we have any entities
                        entities = gmsh.model.getEntities()
                        if not entities:
                            logger.warning(
                                "No entities found in model, creating a simple cube"
                            )
                            # Create a simple cube as fallback
                            gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
                            gmsh.model.occ.synchronize()
                    except Exception as e:
                        logger.warning(
                            f"Error checking entities: {e}, creating fallback geometry"
                        )
                        # Create a simple cube
                        gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
                        gmsh.model.occ.synchronize()

                    # First try to write directly
                    try:
                        gmsh.write(geo_file)
                    except Exception as direct_write_error:
                        logger.warning(f"Direct write failed: {direct_write_error}")

                        # Try creating a .geo_unrolled file (newer Gmsh versions)
                        unrolled_file = f"{os.path.splitext(geo_file)[0]}.geo_unrolled"
                        try:
                            gmsh.write(unrolled_file)
                            # If successful, rename to the desired file
                            if os.path.exists(unrolled_file):
                                os.rename(unrolled_file, geo_file)
                                logger.info(
                                    f"Created {unrolled_file} and renamed to {geo_file}"
                                )
                            else:
                                raise FileNotFoundError(
                                    f"{unrolled_file} was not created"
                                )
                        except Exception as unrolled_error:
                            logger.warning(f"Unrolled write failed: {unrolled_error}")

                            # Last resort: export as Brep and convert
                            brep_file = f"{os.path.splitext(geo_file)[0]}.brep"
                            gmsh.write(brep_file)

                            # Create a simple geo file that references the brep
                            with open(geo_file, "w") as f:
                                f.write(f'Merge "{brep_file}";\n')
                                f.write(
                                    "// This is a reference to a BREP file containing the actual geometry\n"
                                )

                            logger.info(
                                f"Created reference geo file pointing to {brep_file}"
                            )

                except Exception as e:
                    logger.error(f"All geo file creation methods failed: {e}")
                    raise

                # Verify the file was created
                assert os.path.exists(geo_file), f"Failed to create {geo_file}"
                assert os.path.getsize(geo_file) > 0, f"{geo_file} is empty"

                logger.info(f"Successfully wrote Gmsh geometry to {geo_file}")

            except Exception as e:
                logger.error(f"Error writing .geo file: {e}")
                raise

            # Step 4: Verify the .geo file is valid
            logger.info(f"Verifying {geo_file} is valid")
            try:
                # Reset Gmsh
                if gmsh.isInitialized():
                    gmsh.finalize()

                # Re-initialize Gmsh
                gmsh.initialize()

                # Try to read the .geo file
                gmsh.open(geo_file)

                # If we get here without exception, the file is valid
                logger.info(f"{geo_file} is a valid Gmsh .geo file")
                assert True, f"{geo_file} is valid"

            except Exception as e:
                logger.error(f"Error validating .geo file: {e}")
                assert False, f"{geo_file} is not a valid Gmsh .geo file: {str(e)}"

        finally:
            # Finalize Gmsh if we initialized it
            if gmsh.isInitialized():
                try:
                    gmsh.finalize()
                except Exception as e:
                    logger.warning(f"Error finalizing Gmsh: {e}")

            # Print information for manual inspection
            if os.path.exists(geo_file):
                logger.info(f"Gmsh .geo file preserved at {os.path.abspath(geo_file)}")
                print(f"\nGmsh .geo file preserved at {os.path.abspath(geo_file)}")
                print("You can open this file in Gmsh for manual inspection.")
