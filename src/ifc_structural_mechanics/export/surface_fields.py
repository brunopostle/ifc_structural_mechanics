"""Fields of surface members on their mesh, for contours (``94g.13.5``).

CalculiX expands every shell element into a solid as thick as the shell and
reports on the solid's nodes, which lie on the shell's faces and (at its
corners) halfway through. Each of them belongs to the shell node it lies
over. At each shell node the values of its solid nodes are fitted with a
straight line through the thickness ``z``, and integrated over it:

* the translation of the middle surface, in global axes: the line at
  ``z = 0``, where the shell node is;
* membrane forces ``nx``, ``ny``, ``nxy`` per length: the integral of the
  in-plane stresses, tension positive;
* plate moments ``mx``, ``my``, ``mxy`` per length: the integral of those
  stresses times ``z``, positive when the side the surface's ``z`` points to
  is in tension;
* transverse shear ``vx``, ``vy`` per length, from the moments by
  equilibrium: ``vx = dmx/dx + dmxy/dy`` and ``vy = dmxy/dx + dmy/dy``, the
  gradient of each linear triangle averaged at its nodes by area. The
  solver's own transverse shear stress is constant through the thickness
  and too large next to a clamped edge: along ``slab_01``'s it added up to
  12% more than the reaction at a 0.25 m mesh and 20% at 0.5 m, where this
  gives 1.7% and 8% less, and inside the slab it is twice as scattered.

Stresses are turned into the surface's own axes (``surface_axes()``) first.
The thickness at a node is that of its solid nodes, which is the largest of
the members meeting there, as the input writer gives it.
"""

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# Stress components as CalculiX lists them: xx, yy, zz, xy, yz, zx
_TENSOR_INDEX = ((0, 3, 5), (3, 1, 4), (5, 4, 2))

FORCE_KEYS = (
    "nx_N_per_m",
    "ny_N_per_m",
    "nxy_N_per_m",
    "mx_Nm_per_m",
    "my_Nm_per_m",
    "mxy_Nm_per_m",
    "vx_N_per_m",
    "vy_N_per_m",
)
DISPLACEMENT_KEYS = ("ux_m", "uy_m", "uz_m")


def surface_axes(normal: Sequence[float]) -> np.ndarray:
    """The axes surface fields are given in, as rows ``x``, ``y``, ``z``.

    ``z`` is the surface's normal, ``x`` global X laid onto the surface (or
    global Y, where the surface is nearly at right angles to X), and
    ``y = z cross x``.
    """
    z = np.array(normal, dtype=float)
    z /= np.linalg.norm(z)
    for axis in np.eye(3)[:2]:
        x = axis - (axis @ z) * z
        if np.linalg.norm(x) > 0.5:
            break
    x /= np.linalg.norm(x)
    return np.array([x, np.cross(z, x), z])


def triangles(nodes: Sequence[int]) -> List[Tuple[int, int, int]]:
    """Linear triangles through all the nodes of one shell element.

    A six-node triangle is four (corners first, then the middles of the
    sides 1-2, 2-3 and 3-1, as CalculiX numbers them); a quadrilateral two,
    on its corners.
    """
    n = list(nodes)
    if len(n) == 6:
        return [(n[0], n[3], n[5]), (n[3], n[1], n[4]), (n[5], n[4], n[2]),
                (n[3], n[4], n[5])]  # fmt: skip
    if len(n) == 3:
        return [(n[0], n[1], n[2])]
    if len(n) >= 4:
        return [(n[0], n[1], n[2]), (n[0], n[2], n[3])]
    return []


class SurfaceMesh:
    """A surface member's mesh and where its solid nodes lie over it.

    Args:
        elements: ``{element id: shell nodes}`` of the member.
        positions: Positions of the shell nodes.
        element_nodes: The nodes of each expanded element in the result
            file (``ResultsParser.element_nodes``).
        coordinates: Positions of the result file's nodes.
        normal: The member's normal, if the file gives one; else that of its
            first element.
    """

    def __init__(
        self,
        elements: Dict[int, Sequence[int]],
        positions: Dict[int, Sequence[float]],
        element_nodes: Dict[int, Sequence[int]],
        coordinates: Dict[int, Sequence[float]],
        normal: Optional[Sequence[float]] = None,
    ):
        self.nodes: List[int] = sorted(
            {n for nodes in elements.values() for n in nodes}
        )
        index = {node: i for i, node in enumerate(self.nodes)}
        self.points = np.array([positions[n] for n in self.nodes], dtype=float)
        self.triangles = [
            tuple(index[n] for n in triangle)
            for elem in sorted(elements)
            for triangle in triangles(elements[elem])
        ]
        self.axes: Optional[np.ndarray] = None
        # One row per solid node over a shell node: (shell node index,
        # result file node, z)
        owners: List[int] = []
        solid: List[int] = []
        heights: List[float] = []
        seen = set()
        for elem in sorted(elements):
            shell = list(elements[elem])
            expanded = element_nodes.get(elem)
            if not expanded:
                continue
            corners = np.array([positions[n] for n in shell[:3]], dtype=float)
            facing = np.cross(corners[1] - corners[0], corners[2] - corners[0])
            if np.linalg.norm(facing) < 1e-15:
                continue
            facing /= np.linalg.norm(facing)
            if self.axes is None:
                self.axes = surface_axes(normal if normal is not None else facing)
            if facing @ self.axes[2] < 0:
                facing = -facing
            over = np.array([positions[n] for n in shell], dtype=float)
            placed = [n for n in expanded if n in coordinates]
            if not placed:
                continue
            points = np.array([coordinates[n] for n in placed], dtype=float)
            offsets = points[:, None, :] - over[None, :, :]  # (solid, shell, 3)
            across = offsets @ facing
            in_plane = np.linalg.norm(
                offsets - across[:, :, None] * facing[None, None, :], axis=2
            )
            nearest = np.argmin(in_plane, axis=1)
            for node, k, height in zip(
                placed, nearest, across[np.arange(len(placed)), nearest]
            ):
                key = (shell[k], node)
                if key in seen:
                    continue
                seen.add(key)
                owners.append(index[shell[k]])
                solid.append(int(node))
                heights.append(float(height))
        self.owner = np.array(owners, dtype=int)
        self.solid = np.array(solid, dtype=int)
        self.z = np.array(heights, dtype=float)
        count = len(self.nodes)
        self.bottom = np.full(count, np.inf)
        self.top = np.full(count, -np.inf)
        np.minimum.at(self.bottom, self.owner, self.z)
        np.maximum.at(self.top, self.owner, self.z)

    def _line(self, values: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Intercept and slope in ``z`` of each shell node's values, per column."""
        count = len(self.nodes)
        n = np.bincount(self.owner, minlength=count).astype(float)
        sz = np.bincount(self.owner, self.z, minlength=count)
        szz = np.bincount(self.owner, self.z * self.z, minlength=count)
        columns = values.shape[1]
        sv = np.stack(
            [
                np.bincount(self.owner, values[:, c], minlength=count)
                for c in range(columns)
            ],
            axis=1,
        )
        szv = np.stack(
            [
                np.bincount(self.owner, self.z * values[:, c], minlength=count)
                for c in range(columns)
            ],
            axis=1,
        )
        denominator = n * szz - sz * sz
        flat = np.abs(denominator) <= 1e-12 * np.maximum(n * szz, 1e-30)
        safe = np.where(flat, 1.0, denominator)
        slope = np.where(
            flat[:, None], 0.0, (n[:, None] * szv - sz[:, None] * sv) / safe[:, None]
        )
        mean_count = np.maximum(n, 1.0)
        intercept = (sv - slope * sz[:, None]) / mean_count[:, None]
        return intercept, slope

    def displacements(
        self, translations: Dict[int, Sequence[float]]
    ) -> Optional[np.ndarray]:
        """The middle surface's translation at each shell node, or None."""
        try:
            values = np.array([translations[n] for n in self.solid], dtype=float)
        except KeyError:
            return None
        if not len(values):
            return None
        intercept, _ = self._line(values)
        return intercept

    def forces(self, stresses: Dict[int, Sequence[float]]) -> Optional[np.ndarray]:
        """Membrane forces, moments and shears per length at each shell node.

        Columns in the order of ``FORCE_KEYS``; None where a stress is
        missing.
        """
        if self.axes is None:
            return None
        try:
            tensors = np.array([stresses[n] for n in self.solid], dtype=float)
        except KeyError:
            return None
        if not len(tensors):
            return None
        full = tensors[:, _TENSOR_INDEX]
        local = np.einsum("ij,njk,lk->nil", self.axes, full, self.axes)
        # xx, yy, xy, then xz, yz
        values = np.stack(
            [
                local[:, 0, 0],
                local[:, 1, 1],
                local[:, 0, 1],
                local[:, 0, 2],
                local[:, 1, 2],
            ],
            axis=1,
        )
        a, b = self._line(values[:, :3])
        z0, z1 = self.bottom[:, None], self.top[:, None]
        # Integrals over the thickness of a + b z and of (a + b z) z
        force = a * (z1 - z0) + b * (z1**2 - z0**2) / 2.0
        moment = a * (z1**2 - z0**2) / 2.0 + b * (z1**3 - z0**3) / 3.0
        mx, my, mxy = moment[:, 0], moment[:, 1], moment[:, 2]
        d_mx, d_my, d_mxy = self._gradients(np.column_stack([mx, my, mxy]))
        shear = np.column_stack([d_mx[:, 0] + d_mxy[:, 1], d_mxy[:, 0] + d_my[:, 1]])
        return np.column_stack([force, moment, shear])

    def _gradients(self, values: np.ndarray) -> List[np.ndarray]:
        """The gradient in the surface's x and y of each column, at each node.

        Each linear triangle has one; a node has the mean of its triangles'
        weighted by their areas.
        """
        if not hasattr(self, "_slope_operator"):
            local = self.points @ self.axes[:2].T
            corners = np.array(self.triangles, dtype=int).reshape(-1, 3)
            p = local[corners]  # (triangles, 3 corners, 2)
            # Twice the signed area, and the gradient of each corner's
            # linear shape function
            area2 = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (
                p[:, 2, 0] - p[:, 0, 0]
            ) * (p[:, 1, 1] - p[:, 0, 1])
            keep = np.abs(area2) > 0.0
            corners, p, area2 = corners[keep], p[keep], area2[keep]
            following = p[:, [1, 2, 0]] - p[:, [2, 0, 1]]  # opposite edges
            operator = np.stack([following[:, :, 1], -following[:, :, 0]], axis=1)
            self._slope_operator = operator / area2[:, None, None]  # (t, 2, 3)
            self._slope_corners = corners
            self._slope_area = np.abs(area2) / 2.0
            weight = np.zeros(len(self.nodes))
            np.add.at(weight, corners, self._slope_area[:, None])
            self._slope_weight = np.where(weight > 0.0, weight, 1.0)
        corners = self._slope_corners
        gradients = []
        for column in range(values.shape[1]):
            slopes = np.einsum(
                "tij,tj->ti", self._slope_operator, values[corners, column]
            )
            total = np.zeros((len(self.nodes), 2))
            np.add.at(total, corners, (self._slope_area[:, None] * slopes)[:, None, :])
            gradients.append(total / self._slope_weight[:, None])
        return gradients


def rounded(values: Iterable[float]) -> List[float]:
    """Six significant figures, which is what the result file has."""
    return [float(f"{v:.6g}") for v in values]
