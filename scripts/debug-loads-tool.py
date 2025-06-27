#!/usr/bin/env python
"""
Debug tool specifically for troubleshooting load extraction from IFC files.
This tool focuses on the details of how loads are extracted from IFC to the domain model.
"""

import sys
import logging
import json
import click
import ifcopenshell
from typing import Dict, Optional, Any

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("debug_loads")


class LoadDebugger:
    """Focused debugger for load extraction issues."""

    def __init__(self, ifc_file: str):
        """Initialize with an IFC file."""
        self.ifc_file = ifc_file
        self.logger = logger

        # Load the IFC file
        try:
            self.ifc = ifcopenshell.open(ifc_file)
            self.logger.info(f"Successfully loaded IFC file: {ifc_file}")
        except Exception as e:
            self.logger.error(f"Failed to load IFC file: {e}")
            raise

        # Get unit scales
        self.unit_scales = self._get_unit_scales()
        self.logger.info(f"Unit scales: {self.unit_scales}")

    def _get_unit_scales(self) -> Dict[str, float]:
        """Get unit scale factors from the IFC file."""
        unit_scales = {}

        try:
            import ifcopenshell.util.unit

            # Common unit types used in structural analysis
            unit_types = [
                "LENGTHUNIT",
                "FORCEUNIT",
                "PRESSUREUNIT",
                "MOMENTUNIT",
                "MASSUNIT",
                "TIMEUNIT",
            ]

            for unit_type in unit_types:
                try:
                    scale = ifcopenshell.util.unit.calculate_unit_scale(
                        self.ifc, unit_type
                    )
                    unit_scales[unit_type] = scale
                    self.logger.info(f"Unit scale for {unit_type}: {scale}")
                except Exception as e:
                    # If we can't get a specific unit, use default scale (1.0)
                    unit_scales[unit_type] = 1.0
                    self.logger.warning(
                        f"Could not determine scale for {unit_type}, using 1.0: {e}"
                    )
        except Exception as e:
            self.logger.error(f"Error getting unit scales: {e}")
            # Use default values
            unit_scales = {
                "LENGTHUNIT": 1.0,
                "FORCEUNIT": 1.0,
                "PRESSUREUNIT": 1.0,
                "MOMENTUNIT": 1.0,
                "MASSUNIT": 1.0,
                "TIMEUNIT": 1.0,
            }

        return unit_scales

    def examine_all_loads(self, verbose: bool = False) -> Dict[str, Any]:
        """Examine all loads in the IFC file."""
        results = {
            "point_loads": [],
            "line_loads": [],
            "area_loads": [],
            "unprocessed_loads": [],
            "warnings": [],
        }

        # Look for structural point actions
        point_actions = list(self.ifc.by_type("IfcStructuralPointAction"))
        self.logger.info(
            f"Found {len(point_actions)} IfcStructuralPointAction instances"
        )

        for i, action in enumerate(point_actions):
            self.logger.info(f"Examining point action {i+1}:")
            load_info = self._examine_point_action(action, verbose)
            results["point_loads"].append(load_info)

        # Look for structural linear actions
        linear_actions = list(self.ifc.by_type("IfcStructuralLinearAction"))
        self.logger.info(
            f"Found {len(linear_actions)} IfcStructuralLinearAction instances"
        )

        for i, action in enumerate(linear_actions):
            self.logger.info(f"Examining linear action {i+1}:")
            load_info = self._examine_linear_action(action, verbose)
            results["line_loads"].append(load_info)

        # Look for structural planar actions
        planar_actions = list(self.ifc.by_type("IfcStructuralPlanarAction"))
        self.logger.info(
            f"Found {len(planar_actions)} IfcStructuralPlanarAction instances"
        )

        for i, action in enumerate(planar_actions):
            self.logger.info(f"Examining planar action {i+1}:")
            load_info = self._examine_planar_action(action, verbose)
            results["area_loads"].append(load_info)

        # Check for any other load-related entities that might be missed
        other_loads = []
        for entity in self.ifc:
            if "Load" in entity.is_a() or "Action" in entity.is_a():
                if entity.is_a() not in [
                    "IfcStructuralPointAction",
                    "IfcStructuralLinearAction",
                    "IfcStructuralPlanarAction",
                ]:
                    other_loads.append(entity)

        for i, load in enumerate(other_loads):
            self.logger.info(f"Found unprocessed load entity: {load.is_a()}")
            if hasattr(load, "GlobalId"):
                results["unprocessed_loads"].append(
                    {"id": load.GlobalId, "type": load.is_a()}
                )

        return results

    def _examine_point_action(self, action, verbose: bool) -> Dict[str, Any]:
        """Examine a point action in detail."""
        result = {
            "id": action.GlobalId if hasattr(action, "GlobalId") else None,
            "type": action.is_a(),
            "raw": {},
            "processed": {},
            "warnings": [],
        }

        # Get basic info
        if hasattr(action, "Name") and action.Name:
            result["name"] = action.Name

        # Examine applied load
        if hasattr(action, "AppliedLoad") and action.AppliedLoad:
            applied_load = action.AppliedLoad
            result["raw"]["applied_load_type"] = applied_load.is_a()

            # Extract force components
            force_attrs = ["ForceX", "ForceY", "ForceZ"]
            for attr in force_attrs:
                if hasattr(applied_load, attr):
                    value = getattr(applied_load, attr)
                    if value is not None:
                        result["raw"][attr] = value
                        self.logger.info(f"  {attr}: {value}")

            # Extract moment components
            moment_attrs = ["MomentX", "MomentY", "MomentZ"]
            for attr in moment_attrs:
                if hasattr(applied_load, attr):
                    value = getattr(applied_load, attr)
                    if value is not None:
                        result["raw"][attr] = value
                        self.logger.info(f"  {attr}: {value}")

            # Handle special load types
            if applied_load.is_a() == "IfcStructuralLoadSingleForce":
                # Special case for simple_beam.ifc - single force value
                if hasattr(applied_load, "ForceZ") and applied_load.ForceZ is not None:
                    result["raw"]["SingleForceZ"] = applied_load.ForceZ
                    self.logger.info(f"  SingleForceZ: {applied_load.ForceZ}")
        else:
            result["warnings"].append("No AppliedLoad found")
            self.logger.warning("  No AppliedLoad found")

        # Examine position
        if hasattr(action, "ObjectPlacement") and action.ObjectPlacement:
            placement = action.ObjectPlacement
            if hasattr(placement, "RelativePlacement") and placement.RelativePlacement:
                rel_place = placement.RelativePlacement
                if hasattr(rel_place, "Location") and rel_place.Location:
                    location = rel_place.Location
                    if hasattr(location, "Coordinates"):
                        coords = location.Coordinates
                        result["raw"]["position"] = list(coords)
                        self.logger.info(f"  Raw position: {list(coords)}")

                        # Convert position to SI units
                        length_scale = self.unit_scales.get("LENGTHUNIT", 1.0)
                        si_coords = [c * length_scale for c in coords]
                        result["processed"]["position"] = si_coords
                        self.logger.info(f"  Position in SI units: {si_coords}")
                    else:
                        result["warnings"].append("Location has no Coordinates")
                        self.logger.warning("  Location has no Coordinates")
                else:
                    result["warnings"].append("RelativePlacement has no Location")
                    self.logger.warning("  RelativePlacement has no Location")
            else:
                result["warnings"].append("ObjectPlacement has no RelativePlacement")
                self.logger.warning("  ObjectPlacement has no RelativePlacement")
        else:
            result["warnings"].append("No ObjectPlacement found")
            self.logger.warning("  No ObjectPlacement found")

        # Process force magnitude and direction
        force_scale = self.unit_scales.get("FORCEUNIT", 1.0)

        # Method 1: Extract from ForceX, ForceY, ForceZ
        if (
            "ForceX" in result["raw"]
            or "ForceY" in result["raw"]
            or "ForceZ" in result["raw"]
        ):
            force_x = result["raw"].get("ForceX", 0.0) or 0.0
            force_y = result["raw"].get("ForceY", 0.0) or 0.0
            force_z = result["raw"].get("ForceZ", 0.0) or 0.0

            # Scale to SI units
            force_x *= force_scale
            force_y *= force_scale
            force_z *= force_scale

            magnitude = [force_x, force_y, force_z]
            result["processed"]["magnitude_method1"] = magnitude
            self.logger.info(f"  Magnitude (from components): {magnitude}")

            # Calculate direction
            norm = (force_x**2 + force_y**2 + force_z**2) ** 0.5
            if norm > 1e-10:
                direction = [force_x / norm, force_y / norm, force_z / norm]
                result["processed"]["direction_method1"] = direction
                self.logger.info(f"  Direction (from components): {direction}")
            else:
                result["processed"]["direction_method1"] = [0.0, 0.0, -1.0]
                self.logger.info("  Direction (default): [0.0, 0.0, -1.0]")

        # Method 2: Handle IfcStructuralLoadSingleForce special case
        if "SingleForceZ" in result["raw"]:
            force_z = result["raw"]["SingleForceZ"] * force_scale
            magnitude = [0.0, 0.0, force_z]
            result["processed"]["magnitude_method2"] = magnitude
            self.logger.info(f"  Magnitude (from SingleForceZ): {magnitude}")

            # Default direction for vertical load
            direction = [0.0, 0.0, -1.0]
            result["processed"]["direction_method2"] = direction
            self.logger.info(f"  Direction (for SingleForceZ): {direction}")

        # Compute expected domain model load
        if "position" in result["processed"]:
            position = result["processed"]["position"]
        else:
            position = [0.0, 0.0, 0.0]
            result["warnings"].append("Using default position [0,0,0]")
            self.logger.warning("  Using default position [0,0,0]")

        # Use the best available magnitude and direction
        if "magnitude_method2" in result["processed"]:
            magnitude = result["processed"]["magnitude_method2"]
            direction = result["processed"]["direction_method2"]
        elif "magnitude_method1" in result["processed"]:
            magnitude = result["processed"]["magnitude_method1"]
            direction = result["processed"]["direction_method1"]
        else:
            magnitude = [0.0, 0.0, 0.0]
            direction = [0.0, 0.0, -1.0]
            result["warnings"].append(
                "Using default magnitude [0,0,0] and direction [0,0,-1]"
            )
            self.logger.warning(
                "  Using default magnitude [0,0,0] and direction [0,0,-1]"
            )

        result["expected_domain_load"] = {
            "id": result["id"],
            "load_type": "point",
            "magnitude": magnitude,
            "direction": direction,
            "position": position,
        }

        self.logger.info("  Expected domain load:")
        self.logger.info(f"    id: {result['id']}")
        self.logger.info("    load_type: point")
        self.logger.info(f"    magnitude: {magnitude}")
        self.logger.info(f"    direction: {direction}")
        self.logger.info(f"    position: {position}")

        return result

    def _examine_linear_action(self, action, verbose: bool) -> Dict[str, Any]:
        """Examine a linear action in detail."""
        # Similar to _examine_point_action but for line loads
        # Simplified for now
        result = {
            "id": action.GlobalId if hasattr(action, "GlobalId") else None,
            "type": action.is_a(),
            "raw": {},
            "processed": {},
            "warnings": [],
        }

        # Basic info
        if hasattr(action, "Name") and action.Name:
            result["name"] = action.Name

        self.logger.info(
            f"  Linear action {result['id']} - full implementation omitted for brevity"
        )

        return result

    def _examine_planar_action(self, action, verbose: bool) -> Dict[str, Any]:
        """Examine a planar action in detail."""
        # Similar to _examine_point_action but for area loads
        # Simplified for now
        result = {
            "id": action.GlobalId if hasattr(action, "GlobalId") else None,
            "type": action.is_a(),
            "raw": {},
            "processed": {},
            "warnings": [],
        }

        # Basic info
        if hasattr(action, "Name") and action.Name:
            result["name"] = action.Name

        self.logger.info(
            f"  Planar action {result['id']} - full implementation omitted for brevity"
        )

        return result

    def examine_load_groups(self) -> Dict[str, Any]:
        """Examine load groups in the IFC file."""
        results = {"load_groups": [], "load_group_relationships": [], "warnings": []}

        # Find load groups
        load_groups = list(self.ifc.by_type("IfcStructuralLoadGroup"))
        self.logger.info(f"Found {len(load_groups)} IfcStructuralLoadGroup instances")

        for i, group in enumerate(load_groups):
            self.logger.info(f"Examining load group {i+1}:")

            group_info = {
                "id": group.GlobalId if hasattr(group, "GlobalId") else None,
                "type": group.is_a(),
                "loads": [],
            }

            # Get basic info
            if hasattr(group, "Name") and group.Name:
                group_info["name"] = group.Name
                self.logger.info(f"  Name: {group.Name}")

            if hasattr(group, "PredefinedType") and group.PredefinedType:
                group_info["predefined_type"] = group.PredefinedType
                self.logger.info(f"  PredefinedType: {group.PredefinedType}")

            # Find associated loads
            if hasattr(group, "LoadGroupFor"):
                for rel in group.LoadGroupFor:
                    if hasattr(rel, "RelatedStructuralActivity"):
                        load = rel.RelatedStructuralActivity
                        if load:
                            load_id = (
                                load.GlobalId if hasattr(load, "GlobalId") else None
                            )
                            group_info["loads"].append(load_id)

                            # Record relationship
                            results["load_group_relationships"].append(
                                {
                                    "group_id": group_info["id"],
                                    "load_id": load_id,
                                    "relationship_type": rel.is_a(),
                                }
                            )

            self.logger.info(f"  Contains {len(group_info['loads'])} loads")

            results["load_groups"].append(group_info)

        return results


@click.command()
@click.argument(
    "ifc_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=True, dir_okay=False, writable=True),
    help="Output to JSON file (default: print to stdout)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def main(ifc_file: str, output: Optional[str], verbose: bool):
    """
    Debug load extraction from IFC_FILE.

    This tool provides detailed debugging information about load entities
    in an IFC file and how they should be processed into the domain model.
    """
    try:
        click.echo(f"Debugging load extraction from: {ifc_file}")

        # Create debugger
        debugger = LoadDebugger(ifc_file)

        # Examine all loads
        load_results = debugger.examine_all_loads(verbose)

        # Examine load groups
        group_results = debugger.examine_load_groups()

        # Combine results
        results = {**load_results, **group_results}

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(results, f, indent=2)
            click.echo(f"Results written to: {output}")
        else:
            click.echo("\nResults:")
            json_str = json.dumps(results, indent=2)

            # Limit output length for readability
            if len(json_str) > 5000 and not verbose:
                click.echo(
                    json_str[:5000]
                    + "...\n(Output truncated. Use --output for complete results)"
                )
            else:
                click.echo(json_str)

        return 0

    except Exception as e:
        click.echo(f"ERROR: {str(e)}", err=True)
        if verbose:
            import traceback

            click.echo(traceback.format_exc(), err=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
