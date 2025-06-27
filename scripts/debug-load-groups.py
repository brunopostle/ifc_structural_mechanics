#!/usr/bin/env python
"""
Script to analyze and debug load groups and their relationships in the IFC file.

This script specifically focuses on understanding how loads are related to load groups
in the IFC file, which helps debug the issue where loads are being incorrectly
added to a default load group instead of preserving the IFC hierarchy.
"""

import sys
import logging
import json
import click
from typing import Dict, List, Any, Optional
import ifcopenshell

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


class LoadGroupDebugger:
    """Helper class for debugging load groups in IFC files."""

    def __init__(self, ifc_file: str):
        """
        Initialize the debugger with an IFC file.

        Args:
            ifc_file: Path to the IFC file
        """
        self.ifc_file = ifc_file
        self.logger = logger

        # Try to load the IFC file
        try:
            self.ifc = ifcopenshell.open(ifc_file)
            self.logger.info(f"Successfully loaded IFC file: {ifc_file}")
        except Exception as e:
            self.logger.error(f"Failed to load IFC file: {e}")
            raise

    def is_structural_load(self, entity):
        """Check if an entity is a structural load."""
        if entity is None:
            return False

        try:
            if not hasattr(entity, "is_a") or not callable(entity.is_a):
                return False

            load_types = [
                "IfcStructuralPointAction",
                "IfcStructuralLinearAction",
                "IfcStructuralPlanarAction",
                "IfcStructuralLoadCase",
            ]

            return entity.is_a() in load_types
        except Exception as e:
            self.logger.warning(f"Error checking if entity is structural load: {e}")
            return False

    def find_all_load_groups(self) -> List[Dict[str, Any]]:
        """Find all load groups in the IFC file."""
        load_groups = self.ifc.by_type("IfcStructuralLoadGroup")

        result = []
        for group in load_groups:
            group_info = {
                "id": group.id(),
                "GlobalId": group.GlobalId if hasattr(group, "GlobalId") else None,
                "Name": group.Name if hasattr(group, "Name") else None,
                "PredefinedType": (
                    group.PredefinedType if hasattr(group, "PredefinedType") else None
                ),
                "ActionType": (
                    group.ActionType if hasattr(group, "ActionType") else None
                ),
                "ActionSource": (
                    group.ActionSource if hasattr(group, "ActionSource") else None
                ),
                "Coefficient": (
                    group.Coefficient if hasattr(group, "Coefficient") else None
                ),
            }

            result.append(group_info)

        return result

    def find_load_group_relationships(self) -> Dict[str, List[Dict[str, Any]]]:
        """Find relationships between load groups and loads."""
        # Check direct relationships via LoadGroupFor
        result = {"direct_relationships": [], "group_assignments": []}

        # Check LoadGroupFor relationships (direct)
        for group in self.ifc.by_type("IfcStructuralLoadGroup"):
            if hasattr(group, "LoadGroupFor") and group.LoadGroupFor:
                for rel in group.LoadGroupFor:
                    if (
                        hasattr(rel, "RelatedStructuralActivity")
                        and rel.RelatedStructuralActivity
                    ):
                        result["direct_relationships"].append(
                            {
                                "group_id": group.id(),
                                "group_GlobalId": (
                                    group.GlobalId
                                    if hasattr(group, "GlobalId")
                                    else None
                                ),
                                "group_Name": (
                                    group.Name if hasattr(group, "Name") else None
                                ),
                                "load_id": rel.RelatedStructuralActivity.id(),
                                "load_GlobalId": (
                                    rel.RelatedStructuralActivity.GlobalId
                                    if hasattr(
                                        rel.RelatedStructuralActivity, "GlobalId"
                                    )
                                    else None
                                ),
                                "load_Name": (
                                    rel.RelatedStructuralActivity.Name
                                    if hasattr(rel.RelatedStructuralActivity, "Name")
                                    else None
                                ),
                                "load_Type": rel.RelatedStructuralActivity.is_a(),
                                "relationship_type": rel.is_a(),
                            }
                        )

        # Check IfcRelAssignsToGroup relationships (indirect)
        for rel in self.ifc.by_type("IfcRelAssignsToGroup"):
            if hasattr(rel, "RelatingGroup") and hasattr(rel, "RelatedObjects"):
                group = rel.RelatingGroup
                if group.is_a("IfcStructuralLoadGroup"):
                    for obj in rel.RelatedObjects:
                        if self.is_structural_load(obj):
                            result["group_assignments"].append(
                                {
                                    "group_id": group.id(),
                                    "group_GlobalId": (
                                        group.GlobalId
                                        if hasattr(group, "GlobalId")
                                        else None
                                    ),
                                    "group_Name": (
                                        group.Name if hasattr(group, "Name") else None
                                    ),
                                    "load_id": obj.id(),
                                    "load_GlobalId": (
                                        obj.GlobalId
                                        if hasattr(obj, "GlobalId")
                                        else None
                                    ),
                                    "load_Name": (
                                        obj.Name if hasattr(obj, "Name") else None
                                    ),
                                    "load_Type": obj.is_a(),
                                    "relationship_type": rel.is_a(),
                                    "factor": (
                                        rel.Factor if hasattr(rel, "Factor") else None
                                    ),
                                }
                            )

        return result

    def find_all_loads(self) -> List[Dict[str, Any]]:
        """Find all loads in the IFC file."""
        load_types = [
            "IfcStructuralPointAction",
            "IfcStructuralLinearAction",
            "IfcStructuralPlanarAction",
        ]

        result = []
        for load_type in load_types:
            for load in self.ifc.by_type(load_type):
                load_info = {
                    "id": load.id(),
                    "GlobalId": load.GlobalId if hasattr(load, "GlobalId") else None,
                    "Name": load.Name if hasattr(load, "Name") else None,
                    "Type": load.is_a(),
                }

                # Add force information if available
                if hasattr(load, "AppliedLoad") and load.AppliedLoad:
                    applied_load = load.AppliedLoad
                    forces = {}

                    if applied_load.is_a("IfcStructuralLoadSingleForce"):
                        for attr in [
                            "ForceX",
                            "ForceY",
                            "ForceZ",
                            "MomentX",
                            "MomentY",
                            "MomentZ",
                        ]:
                            if hasattr(applied_load, attr):
                                value = getattr(applied_load, attr)
                                if value is not None:
                                    forces[attr] = value

                    load_info["forces"] = forces
                    load_info["applied_load_type"] = applied_load.is_a()

                # Add position if available
                if hasattr(load, "ObjectPlacement") and load.ObjectPlacement:
                    placement = load.ObjectPlacement
                    if (
                        hasattr(placement, "RelativePlacement")
                        and placement.RelativePlacement
                    ):
                        relative = placement.RelativePlacement
                        if hasattr(relative, "Location") and relative.Location:
                            location = relative.Location
                            if hasattr(location, "Coordinates"):
                                load_info["position"] = list(location.Coordinates)

                result.append(load_info)

        return result

    def trace_load_hierarchy(self) -> Dict[str, Any]:
        """
        Trace the complete load hierarchy in the IFC file.

        This includes:
        - Load cases
        - Load groups
        - Loads
        - Load combinations

        And their relationships to each other.
        """
        result = {
            "load_cases": [],
            "load_groups": [],
            "loads": self.find_all_loads(),
            "load_combinations": [],
            "relationships": self.find_load_group_relationships(),
            "load_case_assignments": [],
            "load_combination_assignments": [],
        }

        # Find load cases
        for case in self.ifc.by_type("IfcStructuralLoadCase"):
            case_info = {
                "id": case.id(),
                "GlobalId": case.GlobalId if hasattr(case, "GlobalId") else None,
                "Name": case.Name if hasattr(case, "Name") else None,
                "PredefinedType": (
                    case.PredefinedType if hasattr(case, "PredefinedType") else None
                ),
                "ActionType": case.ActionType if hasattr(case, "ActionType") else None,
                "ActionSource": (
                    case.ActionSource if hasattr(case, "ActionSource") else None
                ),
                "Coefficient": (
                    case.Coefficient if hasattr(case, "Coefficient") else None
                ),
            }

            result["load_cases"].append(case_info)

        # Find load groups
        result["load_groups"] = self.find_all_load_groups()

        # Find load combinations
        for comb in self.ifc.by_type("IfcStructuralLoadGroup"):
            if (
                hasattr(comb, "PredefinedType")
                and comb.PredefinedType == "LOAD_COMBINATION"
            ):
                comb_info = {
                    "id": comb.id(),
                    "GlobalId": comb.GlobalId if hasattr(comb, "GlobalId") else None,
                    "Name": comb.Name if hasattr(comb, "Name") else None,
                    "PredefinedType": comb.PredefinedType,
                    "ActionType": (
                        comb.ActionType if hasattr(comb, "ActionType") else None
                    ),
                    "ActionSource": (
                        comb.ActionSource if hasattr(comb, "ActionSource") else None
                    ),
                    "Coefficient": (
                        comb.Coefficient if hasattr(comb, "Coefficient") else None
                    ),
                }

                result["load_combinations"].append(comb_info)

        # Find load case assignments
        for rel in self.ifc.by_type("IfcRelAssignsToGroup"):
            if hasattr(rel, "RelatingGroup") and hasattr(rel, "RelatedObjects"):
                group = rel.RelatingGroup
                if group.is_a("IfcStructuralLoadCase"):
                    for obj in rel.RelatedObjects:
                        if (
                            obj.is_a("IfcStructuralLoadGroup")
                            and obj.PredefinedType == "LOAD_GROUP"
                        ):
                            result["load_case_assignments"].append(
                                {
                                    "case_id": group.id(),
                                    "case_GlobalId": (
                                        group.GlobalId
                                        if hasattr(group, "GlobalId")
                                        else None
                                    ),
                                    "case_Name": (
                                        group.Name if hasattr(group, "Name") else None
                                    ),
                                    "group_id": obj.id(),
                                    "group_GlobalId": (
                                        obj.GlobalId
                                        if hasattr(obj, "GlobalId")
                                        else None
                                    ),
                                    "group_Name": (
                                        obj.Name if hasattr(obj, "Name") else None
                                    ),
                                    "relationship_type": rel.is_a(),
                                    "factor": (
                                        rel.Factor if hasattr(rel, "Factor") else None
                                    ),
                                }
                            )

        # Find load combination assignments
        for rel in self.ifc.by_type("IfcRelAssignsToGroup"):
            if hasattr(rel, "RelatingGroup") and hasattr(rel, "RelatedObjects"):
                group = rel.RelatingGroup
                if (
                    group.is_a("IfcStructuralLoadGroup")
                    and group.PredefinedType == "LOAD_COMBINATION"
                ):
                    for obj in rel.RelatedObjects:
                        if obj.is_a("IfcStructuralLoadCase"):
                            result["load_combination_assignments"].append(
                                {
                                    "combination_id": group.id(),
                                    "combination_GlobalId": (
                                        group.GlobalId
                                        if hasattr(group, "GlobalId")
                                        else None
                                    ),
                                    "combination_Name": (
                                        group.Name if hasattr(group, "Name") else None
                                    ),
                                    "case_id": obj.id(),
                                    "case_GlobalId": (
                                        obj.GlobalId
                                        if hasattr(obj, "GlobalId")
                                        else None
                                    ),
                                    "case_Name": (
                                        obj.Name if hasattr(obj, "Name") else None
                                    ),
                                    "relationship_type": rel.is_a(),
                                    "factor": (
                                        rel.Factor if hasattr(rel, "Factor") else None
                                    ),
                                }
                            )

        return result


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
    Debug load groups and their relationships in an IFC file.

    This script helps understand how loads are connected to load groups
    in the IFC file, which is important for preserving the hierarchy when
    extracting the domain model.
    """
    try:
        if verbose:
            logger.setLevel(logging.DEBUG)

        logger.info(f"Analyzing load groups in: {ifc_file}")

        # Create debugger
        debugger = LoadGroupDebugger(ifc_file)

        # Trace the load hierarchy
        hierarchy = debugger.trace_load_hierarchy()

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(hierarchy, f, indent=2)
            logger.info(f"Load hierarchy information written to: {output}")
        else:
            # Print summary
            print("\nLoad Hierarchy Summary:")
            print(f"  Loads: {len(hierarchy['loads'])}")
            print(f"  Load Groups: {len(hierarchy['load_groups'])}")
            print(f"  Load Cases: {len(hierarchy['load_cases'])}")
            print(f"  Load Combinations: {len(hierarchy['load_combinations'])}")

            # Print direct relationships
            direct_rels = hierarchy["relationships"]["direct_relationships"]
            group_assigns = hierarchy["relationships"]["group_assignments"]
            print(f"\nDirect Load-Group Relationships: {len(direct_rels)}")
            for i, rel in enumerate(direct_rels[:5]):  # Show just first 5
                print(
                    f"  {i+1}. Group '{rel['group_Name']}' contains load '{rel['load_Name']}'"
                )

            if len(direct_rels) > 5:
                print(f"  ... and {len(direct_rels) - 5} more")

            # Print group assignments
            print(f"\nGroup Assignments: {len(group_assigns)}")
            for i, assign in enumerate(group_assigns[:5]):  # Show just first 5
                print(
                    f"  {i+1}. Group '{assign['group_Name']}' has assigned load '{assign['load_Name']}'"
                )

            if len(group_assigns) > 5:
                print(f"  ... and {len(group_assigns) - 5} more")

            # Print load case assignments
            case_assigns = hierarchy["load_case_assignments"]
            print(f"\nLoad Case Assignments: {len(case_assigns)}")
            for i, assign in enumerate(case_assigns[:5]):  # Show just first 5
                print(
                    f"  {i+1}. Case '{assign['case_Name']}' includes group '{assign['group_Name']}'"
                )

            if len(case_assigns) > 5:
                print(f"  ... and {len(case_assigns) - 5} more")

            # Print load combination assignments
            comb_assigns = hierarchy["load_combination_assignments"]
            print(f"\nLoad Combination Assignments: {len(comb_assigns)}")
            for i, assign in enumerate(comb_assigns[:5]):  # Show just first 5
                factor_str = (
                    f" (factor: {assign['factor']})"
                    if assign.get("factor") is not None
                    else ""
                )
                print(
                    f"  {i+1}. Combination '{assign['combination_Name']}' includes case '{assign['case_Name']}'{factor_str}"
                )

            if len(comb_assigns) > 5:
                print(f"  ... and {len(comb_assigns) - 5} more")

            # Print load details
            print("\nLoad Details:")
            for i, load in enumerate(hierarchy["loads"][:3]):  # Show just first 3
                print(
                    f"  {i+1}. {load['Type']} '{load['Name']}' (GlobalId: {load['GlobalId']})"
                )
                if "forces" in load:
                    print(f"     Forces: {load['forces']}")
                if "position" in load:
                    print(f"     Position: {load['position']}")

            if len(hierarchy["loads"]) > 3:
                print(f"  ... and {len(hierarchy['loads']) - 3} more")

            print(
                "\nFor complete details, use the --output option to save to a JSON file."
            )

        return 0

    except Exception as e:
        logger.error(f"Error: {str(e)}", err=True)
        if verbose:
            import traceback

            logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
