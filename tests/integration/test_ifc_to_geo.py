"""
Test IFC to Gmsh mesh file conversion.

This test reads a simple_beam.ifc file, uses GmshGeometryConverter to convert
the structural model to Gmsh geometry, generates a mesh, and saves the result
as a .msh file for inspection and validation.
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


class TestIFCToMeshConversion:
    """Test the conversion of IFC structural model to Gmsh mesh file."""

    def test_ifc_to_msh_conversion(self):
        """
        Test converting simple_beam.ifc to a Gmsh .msh file.

        This test:
        1. Reads the simple_beam.ifc file
        2. Extracts the structural model
        3. Converts it to Gmsh geometry
        4. Generates a mesh
        5. Saves the result as a .msh file
        6. Verifies the file is valid
        """
        # Define paths
        ifc_path = os.path.join("tests", "test_data", "simple_beam.ifc")

        # Create output directory if it doesn't exist
        output_dir = os.path.join("tests", "output")
        os.makedirs(output_dir, exist_ok=True)

        # Output mesh file path
        msh_file = os.path.join(output_dir, "simple_beam.msh")

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

            # Step 3: Generate mesh
            logger.info("Generating mesh from geometry")
            try:
                # Ensure the model is synchronized before meshing
                gmsh.model.occ.synchronize()

                # Verify we have entities to mesh
                entities = gmsh.model.getEntities()
                assert entities, "No geometric entities found to mesh"
                logger.info(f"Found {len(entities)} entities to mesh")

                # Generate 1D mesh (for curve members like beams)
                gmsh.model.mesh.generate(1)

                # Try to generate 2D mesh if there are surface entities
                try:
                    surface_entities = [e for e in entities if e[0] == 2]
                    if surface_entities:
                        gmsh.model.mesh.generate(2)
                        logger.info("Generated 2D mesh for surface entities")
                except Exception as e:
                    logger.warning(f"Could not generate 2D mesh: {e}")

                logger.info("Mesh generation completed")

            except Exception as e:
                logger.error(f"Error generating mesh: {e}")
                raise

            # Step 4: Write the .msh file
            logger.info(f"Writing mesh to {msh_file}")
            try:
                gmsh.write(msh_file)

                # Verify the file was created
                assert os.path.exists(msh_file), f"Failed to create {msh_file}"
                assert os.path.getsize(msh_file) > 0, f"{msh_file} is empty"

                logger.info(f"Successfully wrote mesh to {msh_file}")

            except Exception as e:
                logger.error(f"Error writing .msh file: {e}")
                raise

            # Step 5: Verify the .msh file is valid by reading it back
            logger.info(f"Verifying {msh_file} is valid")
            try:
                # Reset Gmsh
                if gmsh.isInitialized():
                    gmsh.finalize()

                # Re-initialize Gmsh
                gmsh.initialize()

                # Try to read the .msh file
                gmsh.open(msh_file)

                # Check that we have nodes and elements
                node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
                assert len(node_tags) > 0, "Mesh file contains no nodes"

                element_types, element_tags, element_node_tags = gmsh.model.mesh.getElements()
                assert len(element_types) > 0, "Mesh file contains no elements"

                logger.info(f"Mesh file is valid: {len(node_tags)} nodes, {sum(len(tags) for tags in element_tags)} elements")

            except Exception as e:
                logger.error(f"Error validating .msh file: {e}")
                raise AssertionError(f"{msh_file} is not a valid mesh file: {str(e)}")

        finally:
            # Finalize Gmsh if we initialized it
            if gmsh.isInitialized():
                try:
                    gmsh.finalize()
                except Exception as e:
                    logger.warning(f"Error finalizing Gmsh: {e}")

            # Print information for manual inspection
            if os.path.exists(msh_file):
                logger.info(f"Gmsh mesh file preserved at {os.path.abspath(msh_file)}")
                print(f"\nGmsh mesh file preserved at {os.path.abspath(msh_file)}")
                print("You can open this file in Gmsh for manual inspection.")
