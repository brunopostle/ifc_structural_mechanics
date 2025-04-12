#!/usr/bin/env python
"""
IFC Entity Explorer - Investigate entity relationships in IFC files.

This tool helps explore the relationships between entities in an IFC file,
which is particularly useful for troubleshooting data connections in 
structural analysis models.
"""

import os
import sys
import json
import logging
import click
import ifcopenshell
from typing import Dict, List, Optional, Set, Any, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


class IfcEntityExplorer:
    """Helper class for exploring IFC entity relationships."""

    def __init__(self, ifc_file: str):
        """
        Initialize the explorer with an IFC file.

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

    def get_entity_by_id(
        self, entity_id: str
    ) -> Optional[ifcopenshell.entity_instance]:
        """
        Get an entity by its GlobalId or numeric ID.

        Args:
            entity_id: GlobalId or numeric ID of the entity

        Returns:
            The entity if found, None otherwise
        """
        # Try as GlobalId first
        for entity in self.ifc:
            if hasattr(entity, "GlobalId") and entity.GlobalId == entity_id:
                return entity

        # Try as numeric ID
        try:
            numeric_id = int(entity_id)
            return self.ifc.by_id(numeric_id)
        except (ValueError, RuntimeError):
            pass

        return None

    def explore_entity(
        self, entity: ifcopenshell.entity_instance, max_depth: int = 1
    ) -> Dict[str, Any]:
        """
        Explore an entity's properties and relationships.

        Args:
            entity: The entity to explore
            max_depth: Maximum depth for exploring relationships

        Returns:
            Dictionary containing entity information
        """
        if not entity:
            return {"error": "Entity not found"}

        # Get basic entity info
        result = {
            "id": entity.id(),
            "type": entity.is_a(),
            "attributes": {},
            "inverse_relationships": {},
        }

        # Add GlobalId if available
        if hasattr(entity, "GlobalId"):
            result["global_id"] = entity.GlobalId

        # Add Name if available
        if hasattr(entity, "Name"):
            result["name"] = entity.Name

        # Get direct attributes
        for i, attribute in enumerate(entity):
            # Get attribute name
            attr_name = entity.attribute_name(i)
            attr_value = attribute

            # Handle different attribute types
            if isinstance(attr_value, ifcopenshell.entity_instance):
                result["attributes"][attr_name] = {
                    "id": attr_value.id(),
                    "type": attr_value.is_a(),
                }
                if hasattr(attr_value, "GlobalId"):
                    result["attributes"][attr_name]["global_id"] = attr_value.GlobalId
                if hasattr(attr_value, "Name"):
                    result["attributes"][attr_name]["name"] = attr_value.Name

                # Recursive exploration if depth permits
                if max_depth > 0:
                    result["attributes"][attr_name]["details"] = self.explore_entity(
                        attr_value, max_depth - 1
                    )

            elif (
                isinstance(attr_value, tuple)
                and len(attr_value) > 0
                and isinstance(attr_value[0], ifcopenshell.entity_instance)
            ):
                # Handle tuple of entities (common in IFC)
                entities = []
                for item in attr_value:
                    entity_info = {"id": item.id(), "type": item.is_a()}
                    if hasattr(item, "GlobalId"):
                        entity_info["global_id"] = item.GlobalId
                    if hasattr(item, "Name"):
                        entity_info["name"] = item.Name

                    # Recursive exploration if depth permits
                    if max_depth > 0:
                        entity_info["details"] = self.explore_entity(
                            item, max_depth - 1
                        )

                    entities.append(entity_info)

                result["attributes"][attr_name] = entities

            elif attr_value is not None:
                # Handle simple values
                try:
                    # Convert to basic Python types when possible
                    if isinstance(attr_value, tuple):
                        # Try to convert tuple to list for JSON serialization
                        result["attributes"][attr_name] = list(attr_value)
                    else:
                        result["attributes"][attr_name] = attr_value
                except:
                    # Fall back to string representation if conversion fails
                    result["attributes"][attr_name] = str(attr_value)

        # Get inverse relationships
        try:
            inverse_rels = entity.inverse()
            for rel_name, related_entities in inverse_rels.items():
                # Skip empty relationships
                if not related_entities:
                    continue

                entities = []
                for item in related_entities:
                    entity_info = {"id": item.id(), "type": item.is_a()}
                    if hasattr(item, "GlobalId"):
                        entity_info["global_id"] = item.GlobalId
                    if hasattr(item, "Name"):
                        entity_info["name"] = item.Name

                    # Recursive exploration if depth permits
                    if max_depth > 0:
                        entity_info["details"] = self.explore_entity(
                            item, max_depth - 1
                        )

                    entities.append(entity_info)

                result["inverse_relationships"][rel_name] = entities
        except Exception as e:
            result["inverse_relationships"]["error"] = str(e)

        return result

    def find_path(
        self, start_id: str, target_id: str, max_depth: int = 5
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Find a path between two entities.

        Args:
            start_id: ID or GlobalId of the starting entity
            target_id: ID or GlobalId of the target entity
            max_depth: Maximum depth to search

        Returns:
            List of entities forming a path if found, None otherwise
        """
        # Get the entities
        start_entity = self.get_entity_by_id(start_id)
        target_entity = self.get_entity_by_id(target_id)

        if not start_entity or not target_entity:
            return None

        # Use breadth-first search to find a path
        queue = [(start_entity, [])]
        visited = {start_entity.id()}

        while queue and len(visited) < max_depth * 100:  # Limit total visited nodes
            current, path = queue.pop(0)

            # Check if this is the target
            if current.id() == target_entity.id():
                # Return the path including the target
                return path + [self._entity_to_dict(current)]

            # If path is already at max depth, don't explore further
            if len(path) >= max_depth:
                continue

            # Add current entity to the path
            current_path = path + [self._entity_to_dict(current)]

            # Check direct attributes
            for i, attribute in enumerate(current):
                attr_value = attribute

                # Handle entity instance
                if isinstance(attr_value, ifcopenshell.entity_instance):
                    if attr_value.id() not in visited:
                        visited.add(attr_value.id())
                        queue.append((attr_value, current_path))

                # Handle tuple of entities
                elif (
                    isinstance(attr_value, tuple)
                    and len(attr_value) > 0
                    and isinstance(attr_value[0], ifcopenshell.entity_instance)
                ):
                    for item in attr_value:
                        if item.id() not in visited:
                            visited.add(item.id())
                            queue.append((item, current_path))

            # Check inverse relationships
            try:
                inverse_rels = current.inverse()
                for rel_name, related_entities in inverse_rels.items():
                    for item in related_entities:
                        if item.id() not in visited:
                            visited.add(item.id())
                            queue.append((item, current_path))
            except:
                pass

        # If we get here, no path was found
        return None

    def _entity_to_dict(self, entity: ifcopenshell.entity_instance) -> Dict[str, Any]:
        """Convert an entity to a dictionary with basic info."""
        result = {"id": entity.id(), "type": entity.is_a()}
        if hasattr(entity, "GlobalId"):
            result["global_id"] = entity.GlobalId
        if hasattr(entity, "Name"):
            result["name"] = entity.Name
        return result

    def find_entities_by_type(
        self, entity_type: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Find entities of a specified type.

        Args:
            entity_type: Type of entities to find
            limit: Maximum number of entities to return

        Returns:
            List of dictionaries with entity information
        """
        try:
            entities = list(self.ifc.by_type(entity_type))
            result = []

            for entity in entities[:limit]:
                entity_info = self._entity_to_dict(entity)
                result.append(entity_info)

            return result
        except Exception as e:
            logger.error(f"Error finding entities of type {entity_type}: {e}")
            return []

    def find_structural_model(self) -> Optional[Dict[str, Any]]:
        """
        Find and analyze a structural analysis model in the IFC file.

        Returns:
            Dictionary with model information if found, None otherwise
        """
        analysis_models = list(self.ifc.by_type("IfcStructuralAnalysisModel"))
        if not analysis_models:
            return None

        # Take the first model (usually there's only one)
        model = analysis_models[0]

        result = {
            "id": model.id(),
            "global_id": model.GlobalId if hasattr(model, "GlobalId") else None,
            "name": model.Name if hasattr(model, "Name") else None,
            "description": model.Description if hasattr(model, "Description") else None,
            "model_type": (
                model.PredefinedType if hasattr(model, "PredefinedType") else None
            ),
            "groups": [],
            "members": [],
            "connections": [],
            "loads": [],
        }

        # Get groups
        if hasattr(model, "IsGroupedBy"):
            for group in model.IsGroupedBy:
                if hasattr(group, "RelatedObjects"):
                    group_info = {"id": group.id(), "type": group.is_a(), "objects": []}

                    for obj in group.RelatedObjects:
                        obj_info = self._entity_to_dict(obj)
                        group_info["objects"].append(obj_info)

                    result["groups"].append(group_info)

        # Find structural members
        result["members"] = self.find_entities_by_type("IfcStructuralCurveMember")
        result["members"].extend(
            self.find_entities_by_type("IfcStructuralSurfaceMember")
        )

        # Find connections
        result["connections"] = self.find_entities_by_type(
            "IfcStructuralPointConnection"
        )

        # Find loads
        result["loads"] = self.find_entities_by_type("IfcStructuralPointAction")
        result["loads"].extend(self.find_entities_by_type("IfcStructuralLinearAction"))
        result["loads"].extend(self.find_entities_by_type("IfcStructuralPlanarAction"))

        return result


@click.group()
def cli():
    """IFC Entity Explorer - Investigate entity relationships in IFC files."""
    pass


@cli.command()
@click.argument(
    "ifc_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
)
@click.argument("entity_id", type=str)
@click.option(
    "--depth", "-d", type=int, default=1, help="Exploration depth for relationships"
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=True, dir_okay=False, writable=True),
    help="Output to JSON file (default: print to stdout)",
)
def explore(ifc_file: str, entity_id: str, depth: int, output: Optional[str]):
    """
    Explore an entity and its relationships.

    ENTITY_ID can be a GlobalId or numeric ID.
    """
    try:
        explorer = IfcEntityExplorer(ifc_file)
        entity = explorer.get_entity_by_id(entity_id)

        if not entity:
            click.echo(f"Error: Entity with ID '{entity_id}' not found", err=True)
            return 1

        click.echo(f"Exploring entity: {entity.is_a()} (ID: {entity.id()})")
        if hasattr(entity, "GlobalId"):
            click.echo(f"GlobalId: {entity.GlobalId}")
        if hasattr(entity, "Name"):
            click.echo(f"Name: {entity.Name}")

        # Explore the entity
        result = explorer.explore_entity(entity, max_depth=depth)

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(result, f, indent=2)
            click.echo(f"Entity information written to: {output}")
        else:
            click.echo("\nEntity Details:")
            click.echo(json.dumps(result, indent=2))

        return 0

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        return 1


@cli.command()
@click.argument(
    "ifc_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
)
@click.argument("start_id", type=str)
@click.argument("target_id", type=str)
@click.option("--max-depth", "-d", type=int, default=5, help="Maximum path depth")
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=True, dir_okay=False, writable=True),
    help="Output to JSON file (default: print to stdout)",
)
def find_path(
    ifc_file: str, start_id: str, target_id: str, max_depth: int, output: Optional[str]
):
    """
    Find a path between two entities.

    START_ID and TARGET_ID can be GlobalIds or numeric IDs.
    """
    try:
        explorer = IfcEntityExplorer(ifc_file)

        start_entity = explorer.get_entity_by_id(start_id)
        if not start_entity:
            click.echo(f"Error: Start entity with ID '{start_id}' not found", err=True)
            return 1

        target_entity = explorer.get_entity_by_id(target_id)
        if not target_entity:
            click.echo(
                f"Error: Target entity with ID '{target_id}' not found", err=True
            )
            return 1

        click.echo(
            f"Finding path from {start_entity.is_a()} (ID: {start_entity.id()}) "
            + f"to {target_entity.is_a()} (ID: {target_entity.id()})"
        )

        # Find path
        path = explorer.find_path(start_id, target_id, max_depth=max_depth)

        if not path:
            click.echo(f"No path found between entities within depth {max_depth}")
            return 0

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(path, f, indent=2)
            click.echo(f"Path information written to: {output}")
        else:
            click.echo("\nPath:")
            for i, entity in enumerate(path):
                click.echo(f"{i+1}. {entity['type']} (ID: {entity['id']})")
                if "global_id" in entity:
                    click.echo(f"   GlobalId: {entity['global_id']}")
                if "name" in entity and entity["name"]:
                    click.echo(f"   Name: {entity['name']}")

            click.echo(f"\nComplete path information:")
            click.echo(json.dumps(path, indent=2))

        return 0

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        return 1


@cli.command()
@click.argument(
    "ifc_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
)
@click.argument("entity_type", type=str)
@click.option(
    "--limit", "-l", type=int, default=100, help="Maximum number of entities to return"
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=True, dir_okay=False, writable=True),
    help="Output to JSON file (default: print to stdout)",
)
def find_type(ifc_file: str, entity_type: str, limit: int, output: Optional[str]):
    """
    Find entities of a specific type.

    ENTITY_TYPE is the IFC entity type to find (e.g., IfcStructuralCurveMember).
    """
    try:
        explorer = IfcEntityExplorer(ifc_file)
        entities = explorer.find_entities_by_type(entity_type, limit=limit)

        if not entities:
            click.echo(f"No entities of type '{entity_type}' found")
            return 0

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(entities, f, indent=2)
            click.echo(
                f"Found {len(entities)} entities. Information written to: {output}"
            )
        else:
            click.echo(f"Found {len(entities)} entities of type '{entity_type}':")
            for i, entity in enumerate(entities):
                click.echo(f"{i+1}. ID: {entity['id']}")
                if "global_id" in entity:
                    click.echo(f"   GlobalId: {entity['global_id']}")
                if "name" in entity and entity["name"]:
                    click.echo(f"   Name: {entity['name']}")

            if len(entities) > 10:
                click.echo(
                    "\nShowing first 10 entities only. Use --output for complete list."
                )

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
def analyze_structural(ifc_file: str, output: Optional[str]):
    """
    Analyze the structural analysis model in the IFC file.
    """
    try:
        explorer = IfcEntityExplorer(ifc_file)
        model = explorer.find_structural_model()

        if not model:
            click.echo("No structural analysis model found in the file")
            return 0

        # Output
        if output:
            with open(output, "w") as f:
                json.dump(model, f, indent=2)
            click.echo(f"Structural model information written to: {output}")
        else:
            click.echo(f"Found structural analysis model: {model['name']}")
            click.echo(f"GlobalId: {model['global_id']}")
            if model["description"]:
                click.echo(f"Description: {model['description']}")
            if model["model_type"]:
                click.echo(f"Type: {model['model_type']}")

            click.echo(f"\nModel contains:")
            click.echo(f"  - {len(model['groups'])} groups")
            click.echo(f"  - {len(model['members'])} structural members")
            click.echo(f"  - {len(model['connections'])} structural connections")
            click.echo(f"  - {len(model['loads'])} structural loads")

            click.echo("\nDetailed information available with --output option")

        return 0

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        return 1


if __name__ == "__main__":
    cli()
