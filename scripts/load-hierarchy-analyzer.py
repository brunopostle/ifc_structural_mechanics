#!/usr/bin/env python
"""
IFC Load Hierarchy Analyzer

This script analyzes the hierarchical load structure in an IFC file,
focusing on the relationships between load groups, load cases, and load combinations.
"""

import os
import sys
import json
import logging
import click
from typing import Dict, List, Any, Optional, Set
import ifcopenshell

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


class LoadHierarchyAnalyzer:
    """Helper class for analyzing load hierarchies in IFC files."""

    def __init__(self, ifc_file: str):
        """
        Initialize the analyzer with an IFC file.

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

        # Get unit scales for reference
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

    def find_structural_models(self) -> List[Dict[str, Any]]:
        """Find all structural analysis models in the IFC file."""
        models = self.ifc.by_type("IfcStructuralAnalysisModel")

        result = []
        for model in models:
            model_info = {
                "id": model.id(),
                "GlobalId": model.GlobalId if hasattr(model, "GlobalId") else None,
                "Name": model.Name if hasattr(model, "Name") else None,
                "Description": (
                    model.Description if hasattr(model, "Description") else None
                ),
                "PredefinedType": (
                    model.PredefinedType if hasattr(model, "PredefinedType") else None
                ),
            }

            # Add load information if available
            if hasattr(model, "LoadedBy") and model.LoadedBy:
                model_info["LoadedBy"] = [
                    {
                        "id": item.id(),
                        "GlobalId": (
                            item.GlobalId if hasattr(item, "GlobalId") else None
                        ),
                        "Name": item.Name if hasattr(item, "Name") else None,
                        "PredefinedType": (
                            item.PredefinedType
                            if hasattr(item, "PredefinedType")
                            else None
                        ),
                        "type": item.is_a(),
                    }
                    for item in model.LoadedBy
                ]

            result.append(model_info)

        return result

    def _get_direct_load_groups(self, element) -> List[Dict[str, Any]]:
        """Get load groups directly assigned to an element."""
        if not hasattr(element, "HasAssignments") or not element.HasAssignments:
            return []

        result = []
        for assignment in element.HasAssignments:
            if hasattr(assignment, "RelatingGroup") and assignment.RelatingGroup.is_a(
                "IfcStructuralLoadGroup"
            ):
                group = assignment.RelatingGroup
                result.append(
                    {
                        "id": group.id(),
                        "GlobalId": (
                            group.GlobalId if hasattr(group, "GlobalId") else None
                        ),
                        "Name": group.Name if hasattr(group, "Name") else None,
                        "PredefinedType": (
                            group.PredefinedType
                            if hasattr(group, "PredefinedType")
                            else None
                        ),
                        "ActionType": (
                            group.ActionType if hasattr(group, "ActionType") else None
                        ),
                        "ActionSource": (
                            group.ActionSource
                            if hasattr(group, "ActionSource")
                            else None
                        ),
                        "Coefficient": (
                            group.Coefficient if hasattr(group, "Coefficient") else None
                        ),
                        "assignment_type": assignment.is_a(),
                    }
                )

        return result

    def _get_group_assignments(self, group) -> List[Dict[str, Any]]:
        """Get assignments from a group to other elements."""
        if not hasattr(group, "IsGroupedBy") or not group.IsGroupedBy:
            return []

        result = []
        for rel in group.IsGroupedBy:
            if hasattr(rel, "RelatedObjects") and rel.RelatedObjects:
                for obj in rel.RelatedObjects:
                    result.append(
                        {
                            "id": obj.id(),
                            "GlobalId": (
                                obj.GlobalId if hasattr(obj, "GlobalId") else None
                            ),
                            "Name": obj.Name if hasattr(obj, "Name") else None,
                            "type": obj.is_a(),
                            "relationship_type": rel.is_a(),
                            "factor": rel.Factor if hasattr(rel, "Factor") else None,
                        }
                    )

        return result

    def analyze_load_actions(self) -> Dict[str, Any]:
        """Analyze all load actions in the file."""
        actions = self.ifc.by_type("IfcStructuralAction")

        result = {
            "point_actions": [],
            "linear_actions": [],
            "planar_actions": [],
            "other_actions": [],
        }

        for action in actions:
            action_info = {
                "id": action.id(),
                "GlobalId": action.GlobalId if hasattr(action, "GlobalId") else None,
                "Name": action.Name if hasattr(action, "Name") else None,
                "type": action.is_a(),
                "GlobalOrLocal": (
                    action.GlobalOrLocal if hasattr(action, "GlobalOrLocal") else None
                ),
                "DestabilizingLoad": (
                    action.DestabilizingLoad
                    if hasattr(action, "DestabilizingLoad")
                    else None
                ),
            }

            # Add applied load info if available
            if hasattr(action, "AppliedLoad") and action.AppliedLoad:
                load = action.AppliedLoad
                load_info = {"id": load.id(), "type": load.is_a(), "forces": {}}

                # Extract force components based on load type
                if load.is_a("IfcStructuralLoadSingleForce"):
                    force_attrs = [
                        "ForceX",
                        "ForceY",
                        "ForceZ",
                        "MomentX",
                        "MomentY",
                        "MomentZ",
                    ]
                    for attr in force_attrs:
                        if hasattr(load, attr):
                            value = getattr(load, attr)
                            if value is not None:
                                load_info["forces"][attr] = value

                action_info["applied_load"] = load_info

            # Add position info if available
            if hasattr(action, "ObjectPlacement") and action.ObjectPlacement:
                placement = action.ObjectPlacement
                if (
                    hasattr(placement, "RelativePlacement")
                    and placement.RelativePlacement
                ):
                    rel_place = placement.RelativePlacement
                    if hasattr(rel_place, "Location") and rel_place.Location:
                        location = rel_place.Location
                        if hasattr(location, "Coordinates"):
                            coords = location.Coordinates
                            action_info["raw_position"] = list(coords)

                            # Convert to SI units
                            length_scale = self.unit_scales.get("LENGTHUNIT", 1.0)
                            action_info["position_si"] = [
                                coord * length_scale for coord in coords
                            ]

            # Add group assignments
            action_info["load_groups"] = self._get_direct_load_groups(action)

            # Add to appropriate category
            if action.is_a("IfcStructuralPointAction"):
                result["point_actions"].append(action_info)
            elif action.is_a("IfcStructuralLinearAction"):
                result["linear_actions"].append(action_info)
            elif action.is_a("IfcStructuralPlanarAction"):
                result["planar_actions"].append(action_info)
            else:
                result["other_actions"].append(action_info)

        return result

    def analyze_load_groups(self) -> Dict[str, Any]:
        """Analyze all load groups in the file."""
        load_groups = [
            group
            for group in self.ifc.by_type("IfcStructuralLoadGroup")
            if group.PredefinedType == "LOAD_GROUP"
        ]

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

            # Get assignments (items grouped by this group)
            assignments = self._get_group_assignments(group)
            group_info["assignments"] = assignments

            # Get load cases assigned to this group
            group_info["load_cases"] = self._get_direct_load_groups(group)

            result.append(group_info)

        return result

    def analyze_load_cases(self) -> Dict[str, Any]:
        """Analyze all load cases in the file."""
        load_cases = [
            case
            for case in self.ifc.by_type("IfcStructuralLoadCase")
            if case.PredefinedType == "LOAD_CASE"
        ]

        result = []
        for case in load_cases:
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

            # Get assignments (items grouped by this case)
            assignments = self._get_group_assignments(case)
            case_info["assignments"] = assignments

            result.append(case_info)

        return result

    def analyze_load_combinations(self) -> Dict[str, Any]:
        """Analyze all load combinations in the file."""
        load_combinations = [
            comb
            for comb in self.ifc.by_type("IfcStructuralLoadGroup")
            if comb.PredefinedType == "LOAD_COMBINATION"
        ]

        result = []
        for comb in load_combinations:
            comb_info = {
                "id": comb.id(),
                "GlobalId": comb.GlobalId if hasattr(comb, "GlobalId") else None,
                "Name": comb.Name if hasattr(comb, "Name") else None,
                "PredefinedType": (
                    comb.PredefinedType if hasattr(comb, "PredefinedType") else None
                ),
                "ActionType": comb.ActionType if hasattr(comb, "ActionType") else None,
                "ActionSource": (
                    comb.ActionSource if hasattr(comb, "ActionSource") else None
                ),
                "Coefficient": (
                    comb.Coefficient if hasattr(comb, "Coefficient") else None
                ),
            }

            # Get assignments (items grouped by this combination)
            assignments = self._get_group_assignments(comb)
            comb_info["assignments"] = assignments

            result.append(comb_info)

        return result

    def trace_load(self, load_id: str) -> Dict[str, Any]:
        """
        Trace a load through its hierarchy.

        Args:
            load_id: GlobalId or numeric ID of the load to trace

        Returns:
            Dictionary with the trace information
        """
        # Find the load
        load = None
        try:
            # Try as numeric ID
            load = self.ifc.by_id(int(load_id))
        except ValueError:
            # Try as GlobalId
            for entity in self.ifc.by_type("IfcStructuralAction"):
                if hasattr(entity, "GlobalId") and entity.GlobalId == load_id:
                    load = entity
                    break

        if not load:
            return {"error": f"Load with ID {load_id} not found"}

        # Basic load info
        result = {
            "load": {
                "id": load.id(),
                "GlobalId": load.GlobalId if hasattr(load, "GlobalId") else None,
                "Name": load.Name if hasattr(load, "Name") else None,
                "type": load.is_a(),
            },
            "load_groups": [],
            "load_cases": [],
            "load_combinations": [],
            "applied_by": [],
        }

        # Get applied load info
        if hasattr(load, "AppliedLoad") and load.AppliedLoad:
            applied_load = load.AppliedLoad
            load_info = {
                "id": applied_load.id(),
                "type": applied_load.is_a(),
                "forces": {},
            }

            # Extract force components based on load type
            if applied_load.is_a("IfcStructuralLoadSingleForce"):
                force_attrs = [
                    "ForceX",
                    "ForceY",
                    "ForceZ",
                    "MomentX",
                    "MomentY",
                    "MomentZ",
                ]
                for attr in force_attrs:
                    if hasattr(applied_load, attr):
                        value = getattr(applied_load, attr)
                        if value is not None:
                            load_info["forces"][attr] = value

            result["applied_load"] = load_info

        # Get position
        if hasattr(load, "ObjectPlacement") and load.ObjectPlacement:
            placement = load.ObjectPlacement
            if hasattr(placement, "RelativePlacement") and placement.RelativePlacement:
                rel_place = placement.RelativePlacement
                if hasattr(rel_place, "Location") and rel_place.Location:
                    location = rel_place.Location
                    if hasattr(location, "Coordinates"):
                        coords = location.Coordinates
                        result["raw_position"] = list(coords)

                        # Convert to SI units
                        length_scale = self.unit_scales.get("LENGTHUNIT", 1.0)
                        result["position_si"] = [
                            coord * length_scale for coord in coords
                        ]

        # Trace up through load groups
        if hasattr(load, "HasAssignments") and load.HasAssignments:
            for assignment in load.HasAssignments:
                if hasattr(assignment, "RelatingGroup"):
                    group = assignment.RelatingGroup
                    if (
                        group.is_a("IfcStructuralLoadGroup")
                        and group.PredefinedType == "LOAD_GROUP"
                    ):
                        group_info = {
                            "id": group.id(),
                            "GlobalId": (
                                group.GlobalId if hasattr(group, "GlobalId") else None
                            ),
                            "Name": group.Name if hasattr(group, "Name") else None,
                            "PredefinedType": group.PredefinedType,
                            "ActionType": (
                                group.ActionType
                                if hasattr(group, "ActionType")
                                else None
                            ),
                            "ActionSource": (
                                group.ActionSource
                                if hasattr(group, "ActionSource")
                                else None
                            ),
                            "Coefficient": (
                                group.Coefficient
                                if hasattr(group, "Coefficient")
                                else None
                            ),
                        }

                        # Trace to load cases
                        if hasattr(group, "HasAssignments") and group.HasAssignments:
                            load_cases = []
                            for group_assignment in group.HasAssignments:
                                if hasattr(group_assignment, "RelatingGroup"):
                                    case = group_assignment.RelatingGroup
                                    if (
                                        case.is_a("IfcStructuralLoadCase")
                                        and case.PredefinedType == "LOAD_CASE"
                                    ):
                                        case_info = {
                                            "id": case.id(),
                                            "GlobalId": (
                                                case.GlobalId
                                                if hasattr(case, "GlobalId")
                                                else None
                                            ),
                                            "Name": (
                                                case.Name
                                                if hasattr(case, "Name")
                                                else None
                                            ),
                                            "PredefinedType": case.PredefinedType,
                                            "ActionType": (
                                                case.ActionType
                                                if hasattr(case, "ActionType")
                                                else None
                                            ),
                                            "ActionSource": (
                                                case.ActionSource
                                                if hasattr(case, "ActionSource")
                                                else None
                                            ),
                                            "Coefficient": (
                                                case.Coefficient
                                                if hasattr(case, "Coefficient")
                                                else None
                                            ),
                                        }

                                        # Trace to load combinations
                                        if (
                                            hasattr(case, "HasAssignments")
                                            and case.HasAssignments
                                        ):
                                            combinations = []
                                            for case_assignment in case.HasAssignments:
                                                if hasattr(
                                                    case_assignment, "RelatingGroup"
                                                ):
                                                    comb = case_assignment.RelatingGroup
                                                    if (
                                                        comb.is_a(
                                                            "IfcStructuralLoadGroup"
                                                        )
                                                        and comb.PredefinedType
                                                        == "LOAD_COMBINATION"
                                                    ):
                                                        comb_info = {
                                                            "id": comb.id(),
                                                            "GlobalId": (
                                                                comb.GlobalId
                                                                if hasattr(
                                                                    comb, "GlobalId"
                                                                )
                                                                else None
                                                            ),
                                                            "Name": (
                                                                comb.Name
                                                                if hasattr(comb, "Name")
                                                                else None
                                                            ),
                                                            "PredefinedType": comb.PredefinedType,
                                                            "ActionType": (
                                                                comb.ActionType
                                                                if hasattr(
                                                                    comb, "ActionType"
                                                                )
                                                                else None
                                                            ),
                                                            "ActionSource": (
                                                                comb.ActionSource
                                                                if hasattr(
                                                                    comb, "ActionSource"
                                                                )
                                                                else None
                                                            ),
                                                            "Coefficient": (
                                                                comb.Coefficient
                                                                if hasattr(
                                                                    comb, "Coefficient"
                                                                )
                                                                else None
                                                            ),
                                                        }

                                                        if case_assignment.is_a(
                                                            "IfcRelAssignsToGroupByFactor"
                                                        ):
                                                            comb_info["factor"] = (
                                                                case_assignment.Factor
                                                            )

                                                        combinations.append(comb_info)

                                            case_info["combinations"] = combinations
                                            result["load_combinations"].extend(
                                                combinations
                                            )

                                        load_cases.append(case_info)

                            group_info["cases"] = load_cases
                            result["load_cases"].extend(load_cases)

                        result["load_groups"].append(group_info)

        # Trace the elements this load is applied to
        if hasattr(load, "AppliedOn") and load.AppliedOn:
            for rel in load.AppliedOn:
                if hasattr(rel, "RelatingElement") and rel.RelatingElement:
                    element = rel.RelatingElement
                    element_info = {
                        "id": element.id(),
                        "GlobalId": (
                            element.GlobalId if hasattr(element, "GlobalId") else None
                        ),
                        "Name": element.Name if hasattr(element, "Name") else None,
                        "type": element.is_a(),
                    }

                    result["applied_by"].append(element_info)

        return result


@click.group()
def cli():
    """IFC Load Hierarchy Analyzer - Investigate load structures in IFC files."""
    pass


@cli.command()
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
def analyze_models(ifc_file: str, output: Optional[str]):
    """
    Analyze structural models in an IFC file.
    """
    try:
        analyzer = LoadHierarchyAnalyzer(ifc_file)
        models = analyzer.find_structural_models()

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(models, f, indent=2)
            click.echo(f"Structural model information written to: {output}")
        else:
            if models:
                click.echo(f"Found {len(models)} structural analysis models:")
                for i, model in enumerate(models):
                    click.echo(f"\nModel {i+1}:")
                    click.echo(f"  ID: {model['id']}")
                    click.echo(f"  GlobalId: {model['GlobalId']}")
                    click.echo(f"  Name: {model['Name']}")
                    if model.get("LoadedBy"):
                        click.echo(f"  LoadedBy: {len(model['LoadedBy'])} items")
            else:
                click.echo("No structural analysis models found in the file")

        return 0

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        return 1


@cli.command()
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
def analyze_actions(ifc_file: str, output: Optional[str]):
    """
    Analyze load actions in an IFC file.
    """
    try:
        analyzer = LoadHierarchyAnalyzer(ifc_file)
        actions = analyzer.analyze_load_actions()

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(actions, f, indent=2)
            click.echo(f"Load action information written to: {output}")
        else:
            click.echo("\nLoad Actions Summary:")
            click.echo(f"  Point actions: {len(actions['point_actions'])}")
            click.echo(f"  Linear actions: {len(actions['linear_actions'])}")
            click.echo(f"  Planar actions: {len(actions['planar_actions'])}")
            click.echo(f"  Other actions: {len(actions['other_actions'])}")

            # Show details of point actions
            if actions["point_actions"]:
                click.echo("\nPoint Actions Details:")
                for i, action in enumerate(actions["point_actions"]):
                    click.echo(f"\n  Action {i+1}:")
                    click.echo(f"    ID: {action['id']}")
                    click.echo(f"    GlobalId: {action['GlobalId']}")
                    click.echo(f"    Name: {action['Name']}")

                    if "applied_load" in action:
                        click.echo(
                            f"    Applied Load Type: {action['applied_load']['type']}"
                        )
                        if "forces" in action["applied_load"]:
                            forces = action["applied_load"]["forces"]
                            click.echo(f"    Forces: {forces}")

                    if "position_si" in action:
                        click.echo(f"    Position (SI units): {action['position_si']}")
                    elif "raw_position" in action:
                        click.echo(f"    Position (raw): {action['raw_position']}")

        return 0

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        return 1


@cli.command()
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
def analyze_groups(ifc_file: str, output: Optional[str]):
    """
    Analyze load groups in an IFC file.
    """
    try:
        analyzer = LoadHierarchyAnalyzer(ifc_file)
        groups = analyzer.analyze_load_groups()

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(groups, f, indent=2)
            click.echo(f"Load group information written to: {output}")
        else:
            if groups:
                click.echo(f"\nFound {len(groups)} load groups:")
                for i, group in enumerate(groups):
                    click.echo(f"\nGroup {i+1}:")
                    click.echo(f"  ID: {group['id']}")
                    click.echo(f"  GlobalId: {group['GlobalId']}")
                    click.echo(f"  Name: {group['Name']}")
                    click.echo(f"  PredefinedType: {group['PredefinedType']}")
                    click.echo(f"  ActionType: {group['ActionType']}")

                    if group.get("assignments"):
                        click.echo(f"  Assignments: {len(group['assignments'])} items")

                    if group.get("load_cases"):
                        click.echo(f"  Load Cases: {len(group['load_cases'])} items")
            else:
                click.echo("No load groups found in the file")

        return 0

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        return 1


@cli.command()
@click.argument(
    "ifc_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
)
@click.argument("load_id", type=str)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=True, dir_okay=False, writable=True),
    help="Output to JSON file (default: print to stdout)",
)
def trace_load(ifc_file: str, load_id: str, output: Optional[str]):
    """
    Trace a load through its hierarchy.

    LOAD_ID can be a GlobalId or numeric ID.
    """
    try:
        analyzer = LoadHierarchyAnalyzer(ifc_file)
        trace = analyzer.trace_load(load_id)

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(trace, f, indent=2)
            click.echo(f"Load trace information written to: {output}")
        else:
            if "error" in trace:
                click.echo(f"Error: {trace['error']}")
            else:
                click.echo("\nLoad Trace:")
                click.echo(f"  ID: {trace['load']['id']}")
                click.echo(f"  GlobalId: {trace['load']['GlobalId']}")
                click.echo(f"  Name: {trace['load']['Name']}")
                click.echo(f"  Type: {trace['load']['type']}")

                if "applied_load" in trace:
                    click.echo("\nApplied Load:")
                    click.echo(f"  Type: {trace['applied_load']['type']}")
                    if "forces" in trace["applied_load"]:
                        forces = trace["applied_load"]["forces"]
                        click.echo(f"  Forces: {forces}")

                if "position_si" in trace:
                    click.echo(f"\nPosition (SI units): {trace['position_si']}")

                if trace.get("load_groups"):
                    click.echo(f"\nLoad Groups: {len(trace['load_groups'])}")
                    for i, group in enumerate(trace["load_groups"]):
                        click.echo(
                            f"  Group {i+1}: {group['Name']} (ID: {group['id']})"
                        )

                if trace.get("load_cases"):
                    click.echo(f"\nLoad Cases: {len(trace['load_cases'])}")
                    for i, case in enumerate(trace["load_cases"]):
                        click.echo(f"  Case {i+1}: {case['Name']} (ID: {case['id']})")

                if trace.get("load_combinations"):
                    click.echo(
                        f"\nLoad Combinations: {len(trace['load_combinations'])}"
                    )
                    for i, comb in enumerate(trace["load_combinations"]):
                        factor_str = (
                            f", Factor: {comb['factor']}" if "factor" in comb else ""
                        )
                        click.echo(
                            f"  Combination {i+1}: {comb['Name']} (ID: {comb['id']}){factor_str}"
                        )

                if trace.get("applied_by"):
                    click.echo(f"\nApplied To: {len(trace['applied_by'])}")
                    for i, element in enumerate(trace["applied_by"]):
                        click.echo(
                            f"  Element {i+1}: {element['Name']} (ID: {element['id']}, Type: {element['type']})"
                        )

        return 0

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        return 1


if __name__ == "__main__":
    cli()
