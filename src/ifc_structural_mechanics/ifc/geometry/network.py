"""
Network module for building and manipulating graph structures.

This module provides a Graph class for representing connectivity between
structural elements, supporting topology analysis and visualization.

IMPORTANT NOTE: this code is only intended to work with IFC4, special cases to
handle IFC2X3 are not required

"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class Graph:
    """
    Graph class for building topology networks.

    This class provides functionality to build and analyze graphs of connected
    elements, representing topological relationships in structural models.
    """

    def __init__(self):
        """Initialize an empty graph."""
        self.nodes = {}  # type: Dict[str, Dict[str, Any]]
        self.edges = []  # type: List[Dict[str, Any]]

    def add_node(self, node_id: str, **attrs) -> None:
        """
        Add a node to the graph.

        Args:
            node_id: The unique identifier for the node
            **attrs: Additional attributes to store with the node
        """
        self.nodes[node_id] = attrs

    def add_edge(self, u: str, v: str, **attrs) -> None:
        """
        Add an edge between two nodes.

        Args:
            u: The source node ID
            v: The target node ID
            **attrs: Additional attributes to store with the edge
        """
        self.edges.append({"source": u, "target": v, "attributes": attrs})

    def get_neighbors(self, node_id: str) -> List[str]:
        """
        Get the neighbors of a node.

        Args:
            node_id: The node ID to find neighbors for

        Returns:
            A list of neighboring node IDs
        """
        if node_id not in self.nodes:
            return []

        neighbors = []
        for edge in self.edges:
            if edge["source"] == node_id:
                neighbors.append(edge["target"])
            elif edge["target"] == node_id:
                neighbors.append(edge["source"])

        return neighbors

    def get_node_attributes(self, node_id: str) -> Dict[str, Any]:
        """
        Get the attributes of a node.

        Args:
            node_id: The node ID

        Returns:
            A dictionary of node attributes
        """
        return self.nodes.get(node_id, {})

    def get_edge_attributes(self, u: str, v: str) -> Optional[Dict[str, Any]]:
        """
        Get the attributes of an edge.

        Args:
            u: The source node ID
            v: The target node ID

        Returns:
            A dictionary of edge attributes or None if the edge doesn't exist
        """
        for edge in self.edges:
            if (edge["source"] == u and edge["target"] == v) or (
                edge["source"] == v and edge["target"] == u
            ):
                return edge.get("attributes", {})

        return None

    def get_connected_components(self) -> List[List[str]]:
        """
        Find all connected components in the graph.

        Returns:
            A list of lists, where each inner list contains the nodes
            in a connected component
        """
        visited = set()
        components = []

        def dfs(node, component):
            visited.add(node)
            component.append(node)
            for neighbor in self.get_neighbors(node):
                if neighbor not in visited:
                    dfs(neighbor, component)

        for node in self.nodes:
            if node not in visited:
                component = []
                dfs(node, component)
                components.append(component)

        return components

    def get_node_degree(self, node_id: str) -> int:
        """
        Get the degree (number of connections) of a node.

        Args:
            node_id: The node ID

        Returns:
            The degree of the node
        """
        return len(self.get_neighbors(node_id))

    def find_shortest_path(self, start: str, end: str) -> Optional[List[str]]:
        """
        Find the shortest path between two nodes using BFS.

        Args:
            start: The starting node ID
            end: The ending node ID

        Returns:
            A list of node IDs forming the path, or None if no path exists
        """
        if start not in self.nodes or end not in self.nodes:
            return None

        if start == end:
            return [start]

        visited = {start}
        queue = [(start, [start])]

        while queue:
            current, path = queue.pop(0)

            for neighbor in self.get_neighbors(current):
                if neighbor == end:
                    return path + [neighbor]

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None  # No path found
