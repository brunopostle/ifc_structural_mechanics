"""Euler-Bernoulli beam stiffness matrix for CalculiX U1 user elements.

CalculiX *BEAM SECTION with SECTION=GENERAL only works for U1 (user-defined)
elements, not B31.  For non-standard cross-sections (I, T, L, C, arbitrary),
this module computes the full 12×12 global Euler-Bernoulli stiffness matrix and
writes it as a *MATRIX block in the INP file.

DOF ordering (per node, 6 DOFs each, two nodes = 12 total):
    [u, v, w, θx, θy, θz]
where
    u   = displacement along local x (beam axis)
    v   = displacement along local y
    w   = displacement along local z
    θx  = twist (torsion) about local x
    θy  = rotation about local y  (sign convention: θy = -dw/dx)
    θz  = rotation about local z  (sign convention: θz = +dv/dx)

Global indices: node 1 → 0-5, node 2 → 6-11.
"""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np


def euler_bernoulli_stiffness_local(
    L: float,
    EA: float,
    EIy: float,
    EIz: float,
    GJ: float,
) -> np.ndarray:
    """12×12 Euler-Bernoulli beam stiffness matrix in local coordinates.

    Args:
        L:   Element length (m).
        EA:  Axial stiffness (N).
        EIy: Bending stiffness about local y (N·m²).
        EIz: Bending stiffness about local z (N·m²).
        GJ:  Torsional stiffness (N·m²).

    Returns:
        12×12 symmetric stiffness matrix.
    """
    K = np.zeros((12, 12))

    # --- Axial (u1=0, u2=6) ---
    K[0, 0] = K[6, 6] = EA / L
    K[0, 6] = K[6, 0] = -EA / L

    # --- Bending in x-y plane (EIz) ---
    # DOFs: v1=1, θz1=5, v2=7, θz2=11  (θz = +dv/dx)
    c1 = 12.0 * EIz / L**3
    c2 = 6.0 * EIz / L**2
    c3 = 4.0 * EIz / L
    c4 = 2.0 * EIz / L
    K[1, 1] = K[7, 7] = c1
    K[1, 7] = K[7, 1] = -c1
    K[1, 5] = K[5, 1] = c2
    K[1, 11] = K[11, 1] = c2
    K[5, 7] = K[7, 5] = -c2
    K[11, 7] = K[7, 11] = -c2
    K[5, 5] = K[11, 11] = c3
    K[5, 11] = K[11, 5] = c4

    # --- Bending in x-z plane (EIy) ---
    # DOFs: w1=2, θy1=4, w2=8, θy2=10  (θy = -dw/dx → sign flips on coupling)
    d1 = 12.0 * EIy / L**3
    d2 = 6.0 * EIy / L**2
    d3 = 4.0 * EIy / L
    d4 = 2.0 * EIy / L
    K[2, 2] = K[8, 8] = d1
    K[2, 8] = K[8, 2] = -d1
    K[2, 4] = K[4, 2] = -d2   # negative: θy = -dw/dx
    K[2, 10] = K[10, 2] = -d2
    K[4, 8] = K[8, 4] = d2
    K[10, 8] = K[8, 10] = d2
    K[4, 4] = K[10, 10] = d3
    K[4, 10] = K[10, 4] = d4

    # --- Torsion (θx1=3, θx2=9) ---
    K[3, 3] = K[9, 9] = GJ / L
    K[3, 9] = K[9, 3] = -GJ / L

    return K


def local_to_global_transform(
    node1: Sequence[float],
    node2: Sequence[float],
    beam_normal: Sequence[float],
) -> Tuple[np.ndarray, float]:
    """Build the 12×12 rotation matrix T and element length L.

    T maps global DOF vectors to local: v_local = T @ v_global.
    K_global = T.T @ K_local @ T.

    The local coordinate system is:
        e1 = normalise(node2 - node1)          (beam axis, local x)
        e2 = orthogonalised beam_normal         (local y)
        e3 = cross(e1, e2)                      (local z)

    Args:
        node1, node2: 3D coordinates of the two end nodes (m).
        beam_normal:  Preferred direction for local y (from *BEAM SECTION normal).

    Returns:
        (T, L) where T is the 12×12 rotation matrix and L is element length.
    """
    p1 = np.asarray(node1, dtype=float)
    p2 = np.asarray(node2, dtype=float)
    axis = p2 - p1
    L = float(np.linalg.norm(axis))
    if L < 1e-12:
        raise ValueError(f"Zero-length beam element between {node1} and {node2}")
    e1 = axis / L

    # Orthogonalise beam_normal against e1 to get local y
    n = np.asarray(beam_normal, dtype=float)
    n = n - np.dot(n, e1) * e1
    n_len = float(np.linalg.norm(n))
    if n_len < 1e-10:
        # beam_normal is parallel to beam axis — pick an arbitrary perpendicular
        for candidate in ([0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]):
            n = np.array(candidate) - np.dot(np.array(candidate), e1) * e1
            n_len = float(np.linalg.norm(n))
            if n_len > 1e-10:
                break
    e2 = n / n_len
    e3 = np.cross(e1, e2)

    # Direction cosine matrix Λ: rows are local axes expressed in global coords
    Lambda = np.array([e1, e2, e3])  # 3×3

    # Block-diagonal 12×12: four copies for [trans1, rot1, trans2, rot2]
    T = np.zeros((12, 12))
    for i in range(4):
        T[3 * i : 3 * i + 3, 3 * i : 3 * i + 3] = Lambda

    return T, L


def euler_bernoulli_stiffness_global(
    node1: Sequence[float],
    node2: Sequence[float],
    beam_normal: Sequence[float],
    EA: float,
    EIy: float,
    EIz: float,
    GJ: float,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """Compute global stiffness matrix for a 3D Euler-Bernoulli beam element.

    Args:
        node1, node2: End-node coordinates (m).
        beam_normal:  Local y direction (beam orientation normal).
        EA:   Axial stiffness (N).
        EIy:  Bending stiffness about local y (N·m²).
        EIz:  Bending stiffness about local z (N·m²).
        GJ:   Torsional stiffness (N·m²).

    Returns:
        (K_global, T, L) — 12×12 global stiffness matrix, 12×12 rotation matrix,
        element length.
    """
    T, L = local_to_global_transform(node1, node2, beam_normal)
    K_local = euler_bernoulli_stiffness_local(L, EA, EIy, EIz, GJ)
    K_global = T.T @ K_local @ T
    return K_global, T, L


def work_equivalent_loads_global(
    q_global: Sequence[float],
    L: float,
    T: np.ndarray,
) -> np.ndarray:
    """Compute work-equivalent nodal load vector (12-element, global) for a
    uniform distributed load.

    Args:
        q_global: Force per unit length in global [x, y, z] (N/m).
        L:        Element length (m).
        T:        12×12 rotation matrix from :func:`local_to_global_transform`.

    Returns:
        12-element array [F1, M1, F2, M2] in global coordinates.
    """
    # Transform load to local coordinates using the top-left 3×3 block of T
    Lambda = T[:3, :3]
    qx, qy, qz = Lambda @ np.asarray(q_global, dtype=float)

    # Work-equivalent nodal loads in local coords (Euler-Bernoulli shape functions)
    # Node 1: indices [u1, v1, w1, θx1, θy1, θz1]
    # Node 2: indices [u2, v2, w2, θx2, θy2, θz2]
    f_local = np.array([
        qx * L / 2,          # u1
        qy * L / 2,          # v1
        qz * L / 2,          # w1
        0.0,                 # θx1  (no torsion from uniform transverse load)
        -qz * L**2 / 12,    # θy1  (θy = -dw/dx sign convention)
        qy * L**2 / 12,     # θz1
        qx * L / 2,          # u2
        qy * L / 2,          # v2
        qz * L / 2,          # w2
        0.0,                 # θx2
        qz * L**2 / 12,     # θy2
        -qy * L**2 / 12,    # θz2
    ])

    return T.T @ f_local


def lower_triangular_entries(K: np.ndarray) -> list[float]:
    """Return the lower-triangular entries (incl. diagonal) of a symmetric matrix.

    CalculiX *MATRIX expects entries row-by-row for the lower triangle::

        k11
        k21, k22
        k31, k32, k33
        ...

    Returns a flat list in that order (78 entries for a 12×12 matrix).
    """
    n = K.shape[0]
    entries: list[float] = []
    for i in range(n):
        for j in range(i + 1):
            entries.append(float(K[i, j]))
    return entries


def format_matrix_block(K: np.ndarray, values_per_line: int = 6) -> str:
    """Format a symmetric matrix as a CalculiX *MATRIX data block.

    Entries are the lower triangle, row by row, formatted in scientific notation.

    Args:
        K:               12×12 symmetric stiffness matrix.
        values_per_line: How many comma-separated values per line.

    Returns:
        Multi-line string ready to write after the ``*MATRIX`` keyword line.
    """
    entries = lower_triangular_entries(K)
    lines: list[str] = []
    for i in range(0, len(entries), values_per_line):
        chunk = entries[i : i + values_per_line]
        lines.append(", ".join(f"{v:.6e}" for v in chunk))
    return "\n".join(lines) + "\n"
