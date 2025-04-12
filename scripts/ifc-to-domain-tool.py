#!/usr/bin/env python
"""
CLI tool to extract domain model from an IFC file and output it as YAML.

This tool uses the ifc_structural_mechanics library to extract a structural
domain model from an IFC file and outputs it in YAML format for inspection.
"""

import os
import sys
import yaml
import logging
import click
import numpy as np
import ifcopenshell
from typing import Any, Dict, List, Optional, Union

# Import the library components needed
from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_connection import (
    PointConnection,
    RigidConnection,
    HingeConnection,
)
from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.load import (
    Load,
    PointLoad,
    LineLoad,
    AreaLoad,
    LoadGroup,
    LoadCombination,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


class NumpyArrayEncoder(yaml.SafeDumper):
    """Custom YAML encoder that handles NumPy arrays and other special types."""

    def represent_numpy_ndarray(self, data):
        """Convert numpy arrays to lists for YAML serialization."""
        return self.represent_sequence("tag:yaml.org,2002:seq", data.tolist())

    def represent_material(self, data):
        """Convert Material objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "name": data.name,
                "density": float(data.density),
                "elastic_modulus": float(data.elastic_modulus),
                "poisson_ratio": float(data.poisson_ratio),
                "thermal_expansion_coefficient": data.thermal_expansion_coefficient,
                "yield_strength": data.yield_strength,
                "ultimate_strength": data.ultimate_strength,
            },
        )

    def represent_section(self, data):
        """Convert Section objects to dictionaries."""
        result = {
            "id": data.id,
            "name": data.name,
            "section_type": data.section_type,
            "area": float(data.area),
            "dimensions": {k: float(v) for k, v in data.dimensions.items()},
        }

        # Add calculated properties if available
        for prop in [
            "moment_of_inertia_y",
            "moment_of_inertia_z",
            "torsional_constant",
            "warping_constant",
            "shear_area_y",
            "shear_area_z",
        ]:
            if hasattr(data, prop) and getattr(data, prop) is not None:
                result[prop] = float(getattr(data, prop))

        return self.represent_mapping("tag:yaml.org,2002:map", result)

    def represent_thickness(self, data):
        """Convert Thickness objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "name": data.name,
                "value": float(data.value),
                "is_variable": data.is_variable,
                "min_value": None if data.min_value is None else float(data.min_value),
                "max_value": None if data.max_value is None else float(data.max_value),
            },
        )

    def represent_curve_member(self, data):
        """Convert CurveMember objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "type": data.type,
                "geometry": self._clean_for_yaml(data.geometry),
                "material": data.material,
                "section": data.section,
                "boundary_conditions": self._clean_for_yaml(data.boundary_conditions),
                "loads": self._clean_for_yaml(data.loads),
            },
        )

    def represent_surface_member(self, data):
        """Convert SurfaceMember objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "type": data.type,
                "geometry": self._clean_for_yaml(data.geometry),
                "material": data.material,
                "thickness": data.thickness,
                "boundary_conditions": self._clean_for_yaml(data.boundary_conditions),
                "loads": self._clean_for_yaml(data.loads),
            },
        )

    def represent_point_connection(self, data):
        """Convert PointConnection objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "connection_type": data.connection_type,
                "position": self._clean_for_yaml(data.position),
                "connected_members": data.connected_members,
            },
        )

    def represent_rigid_connection(self, data):
        """Convert RigidConnection objects to dictionaries."""
        result = {
            "id": data.id,
            "connection_type": data.connection_type,
            "connected_members": data.connected_members,
        }
        if hasattr(data, "position") and data.position is not None:
            result["position"] = self._clean_for_yaml(data.position)
        return self.represent_mapping("tag:yaml.org,2002:map", result)

    def represent_hinge_connection(self, data):
        """Convert HingeConnection objects to dictionaries."""
        result = {
            "id": data.id,
            "connection_type": data.connection_type,
            "position": self._clean_for_yaml(data.position),
            "connected_members": data.connected_members,
        }
        if hasattr(data, "rotation_axis") and data.rotation_axis is not None:
            result["rotation_axis"] = self._clean_for_yaml(data.rotation_axis)
        return self.represent_mapping("tag:yaml.org,2002:map", result)

    def represent_point_load(self, data):
        """Convert PointLoad objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "load_type": data.load_type,
                "magnitude": self._clean_for_yaml(data.magnitude),
                "direction": self._clean_for_yaml(data.direction),
                "position": self._clean_for_yaml(data.position),
            },
        )

    def represent_line_load(self, data):
        """Convert LineLoad objects to dictionaries."""
        result = {
            "id": data.id,
            "load_type": data.load_type,
            "magnitude": self._clean_for_yaml(data.magnitude),
            "direction": self._clean_for_yaml(data.direction),
            "start_position": self._clean_for_yaml(data.start_position),
            "end_position": self._clean_for_yaml(data.end_position),
            "distribution": data.distribution,
        }
        if hasattr(data, "start_magnitude") and data.start_magnitude is not None:
            result["start_magnitude"] = self._clean_for_yaml(data.start_magnitude)
        if hasattr(data, "end_magnitude") and data.end_magnitude is not None:
            result["end_magnitude"] = self._clean_for_yaml(data.end_magnitude)
        return self.represent_mapping("tag:yaml.org,2002:map", result)

    def represent_area_load(self, data):
        """Convert AreaLoad objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "load_type": data.load_type,
                "magnitude": self._clean_for_yaml(data.magnitude),
                "direction": self._clean_for_yaml(data.direction),
                "surface_reference": data.surface_reference,
                "distribution": data.distribution,
            },
        )

    def represent_load_group(self, data):
        """Convert LoadGroup objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "name": data.name,
                "description": data.description,
                "loads": self._clean_for_yaml(data.loads),
            },
        )

    def represent_load_combination(self, data):
        """Convert LoadCombination objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "name": data.name,
                "description": data.description,
                "load_groups": self._clean_for_yaml(data.load_groups),
            },
        )

    def represent_structural_model(self, data):
        """Convert StructuralModel objects to dictionaries."""
        return self.represent_mapping(
            "tag:yaml.org,2002:map",
            {
                "id": data.id,
                "name": data.name,
                "description": data.description,
                "members": data.members,
                "connections": data.connections,
                "load_groups": data.load_groups,
                "load_combinations": data.load_combinations,
                "results": data.results,
            },
        )

    def _clean_for_yaml(self, data: Any) -> Any:
        """Clean an object for YAML serialization."""
        if isinstance(data, np.ndarray):
            return data.tolist()
        elif isinstance(data, (list, tuple)):
            return [self._clean_for_yaml(item) for item in data]
        elif isinstance(data, dict):
            return {k: self._clean_for_yaml(v) for k, v in data.items()}
        return data


# Register representation functions
NumpyArrayEncoder.add_representer(np.ndarray, NumpyArrayEncoder.represent_numpy_ndarray)
NumpyArrayEncoder.add_representer(Material, NumpyArrayEncoder.represent_material)
NumpyArrayEncoder.add_representer(Section, NumpyArrayEncoder.represent_section)
NumpyArrayEncoder.add_representer(Thickness, NumpyArrayEncoder.represent_thickness)
NumpyArrayEncoder.add_representer(CurveMember, NumpyArrayEncoder.represent_curve_member)
NumpyArrayEncoder.add_representer(
    SurfaceMember, NumpyArrayEncoder.represent_surface_member
)
NumpyArrayEncoder.add_representer(
    PointConnection, NumpyArrayEncoder.represent_point_connection
)
NumpyArrayEncoder.add_representer(
    RigidConnection, NumpyArrayEncoder.represent_rigid_connection
)
NumpyArrayEncoder.add_representer(
    HingeConnection, NumpyArrayEncoder.represent_hinge_connection
)
NumpyArrayEncoder.add_representer(PointLoad, NumpyArrayEncoder.represent_point_load)
NumpyArrayEncoder.add_representer(LineLoad, NumpyArrayEncoder.represent_line_load)
NumpyArrayEncoder.add_representer(AreaLoad, NumpyArrayEncoder.represent_area_load)
NumpyArrayEncoder.add_representer(LoadGroup, NumpyArrayEncoder.represent_load_group)
NumpyArrayEncoder.add_representer(
    LoadCombination, NumpyArrayEncoder.represent_load_combination
)
NumpyArrayEncoder.add_representer(
    StructuralModel, NumpyArrayEncoder.represent_structural_model
)


def model_to_yaml(model: StructuralModel) -> str:
    """
    Convert a domain model to YAML string.

    Args:
        model: The structural domain model

    Returns:
        YAML string representation of the model
    """

    # Create a custom dumper class that inherits from our NumpyArrayEncoder
    class NoAliasesDumper(NumpyArrayEncoder):
        def ignore_aliases(self, data):
            # Always return True to ignore aliases (disable anchors)
            return True

    return yaml.dump(
        model, Dumper=NoAliasesDumper, default_flow_style=False, sort_keys=False
    )


@click.command()
@click.argument(
    "ifc_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=True, dir_okay=False, writable=True),
    help="Output YAML file (default: print to stdout)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def main(ifc_file: str, output: Optional[str], verbose: bool):
    """
    Extract domain model from IFC_FILE and output it as YAML.

    This tool extracts a structural domain model from an IFC file using the
    ifc_structural_mechanics library and outputs it as YAML for inspection.
    """
    # Set logging level based on verbosity
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        click.echo(f"Processing IFC file: {ifc_file}")

        # Load the IFC file
        ifc = ifcopenshell.open(ifc_file)

        # Create an extractor
        extractor = Extractor(ifc)

        # Extract the model
        click.echo("Extracting structural model...")
        model = extractor.extract_model()

        # Print model info
        click.echo(f"Extracted model: {model.name if model.name else model.id}")
        click.echo(f"  Members: {len(model.members)}")
        click.echo(f"  Connections: {len(model.connections)}")
        click.echo(f"  Load groups: {len(model.load_groups)}")

        # Convert to YAML
        click.echo("Converting to YAML...")
        yaml_str = model_to_yaml(model)

        # Output
        if output:
            with open(output, "w") as f:
                f.write(yaml_str)
            click.echo(f"YAML model written to: {output}")
        else:
            click.echo("\n--- YAML Model ---")
            click.echo(yaml_str)

        return 0

    except ImportError as e:
        click.echo(f"ERROR: Missing required module: {e}", err=True)
        return 1
    except ifcopenshell.SchemaError as e:
        click.echo(f"ERROR: Invalid IFC schema: {e}", err=True)
        return 2
    except Exception as e:
        click.echo(f"ERROR: {str(e)}", err=True)
        if verbose:
            import traceback

            click.echo(traceback.format_exc(), err=True)
        return 3


if __name__ == "__main__":
    sys.exit(main())
