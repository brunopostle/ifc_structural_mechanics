"""Pictures of an analysis, drawn with PyVista.

``render()`` draws one picture of an output directory (``AnalysisOutput``):

- a deformed shape over the undeformed model, coloured by the size of the
  displacement or by von Mises stress, for a load case, a combination or a
  mode;
- or a section force diagram (N, Vf1, Vf2, T, Mf1, Mf2) along every curve
  member, drawn from ``results.json`` on the side of the section axis it
  refers to, so that a bending moment is on the tension side;
- with the supports, the reactions and the loads written to the solver.

The deformation is scaled up so that the largest is a fixed share of the
model's size, and the picture says by how much.
"""

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import pyvista as pv

    PYVISTA_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the environment
    PYVISTA_AVAILABLE = False

from .output_files import (
    SURFACE_CELLS,
    VTK_QUADRATIC_EDGE,
    VTK_QUADRATIC_TRIANGLE,
    AnalysisOutput,
)

FIELDS = ("displacement", "von_mises")
DIAGRAMS = ("N", "Vf1", "Vf2", "T", "Mf1", "Mf2")
VIEWS = ("auto", "iso", "xy", "xz", "yz")

# Diagram name, unit factor and unit; the axis of the section it is drawn along
_DIAGRAM_KEYS = {
    "N": ("N_N", 1e-3, "kN", "1"),
    "Vf1": ("Vf1_N", 1e-3, "kN", "1"),
    "Vf2": ("Vf2_N", 1e-3, "kN", "2"),
    "T": ("T_Nm", 1e-3, "kN·m", "1"),
    "Mf1": ("Mf1_Nm", 1e-3, "kN·m", "1"),
    "Mf2": ("Mf2_Nm", 1e-3, "kN·m", "2"),
}
_DIAGRAM_TITLES = {
    "N": "Axial force N",
    "Vf1": "Shear force Vf1",
    "Vf2": "Shear force Vf2",
    "T": "Torque T",
    "Mf1": "Bending moment Mf1",
    "Mf2": "Bending moment Mf2",
}

# Share of the model's size that the largest of each thing is drawn as
_DEFORMATION_SHARE = 0.06
_DIAGRAM_SHARE = 0.12
_ARROW_SHARE = 0.15
_GLYPH_SHARE = 0.012

_GHOST = "#9aa0a6"
_MEMBER = "#5f6368"
_SUPPORT = "#1a73e8"
_REACTION = "#188038"
_LOAD = "#d93025"
_TEXT = "#202124"


def _require_pyvista() -> None:
    if not PYVISTA_AVAILABLE:
        raise ImportError(
            "Plotting needs PyVista: pip install 'ifc_structural_mechanics[viz]'"
        )


def _linear_cells(
    cells: Sequence[Tuple[int, List[int]]],
) -> Tuple[List[List[int]], List[List[int]], List[List[int]]]:
    """Split quadratic cells into linear ones through all their nodes.

    Returns:
        Line segments, triangles, and the segments of the triangles' edges.
    """
    segments, triangles, edges = [], [], []
    for cell_type, nodes in cells:
        if cell_type == VTK_QUADRATIC_EDGE:
            start, end, middle = nodes
            segments += [[start, middle], [middle, end]]
        elif cell_type == VTK_QUADRATIC_TRIANGLE:
            a, b, c, ab, bc, ca = nodes
            triangles += [[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]]
            edges += [[a, ab], [ab, b], [b, bc], [bc, c], [c, ca], [ca, a]]
        elif cell_type in SURFACE_CELLS:
            a, b, c = nodes
            triangles.append([a, b, c])
            edges += [[a, b], [b, c], [c, a]]
        else:
            segments.append(list(nodes))
    # Neighbouring triangles share an edge: once each
    edges = [list(edge) for edge in sorted({tuple(sorted(e)) for e in edges})]
    return segments, triangles, edges


def _poly(points: np.ndarray, lines=(), faces=()) -> "pv.PolyData":
    """Lines or faces on points, with no vertex cells (PyVista gives a bare
    set of points one per point, which draws every node as a dot)."""
    cells = {}
    if len(lines):
        cells["lines"] = np.hstack([[len(c)] + list(c) for c in lines])
    if len(faces):
        cells["faces"] = np.hstack([[len(c)] + list(c) for c in faces])
    return pv.PolyData(np.asarray(points, dtype=float), **cells)


def _size(points: np.ndarray) -> float:
    extent = points.max(axis=0) - points.min(axis=0)
    return float(np.linalg.norm(extent)) or 1.0


def _flat_axis(points: np.ndarray) -> Optional[int]:
    """The axis a plane model is flat along; for a model along one axis, the
    horizontal one of the two, so that it is seen from the side."""
    extent = points.max(axis=0) - points.min(axis=0)
    flat = [axis for axis in range(3) if extent[axis] <= 0.02 * extent.max()]
    if len(flat) == 2:
        flat = [axis for axis in flat if axis != 2]
    return flat[0] if len(flat) == 1 else None


def _count(number: int, noun: str) -> str:
    return f"{number:,} {noun}{'' if number == 1 else 's'}"


def _case_label(case, combination, mode, output: AnalysisOutput) -> str:
    if mode is not None:
        modes = output.modes
        entry = modes[mode - 1] if mode - 1 < len(modes) else {}
        if "frequency_Hz" in entry:
            return f"Mode {mode}: {entry['frequency_Hz']:.3g} Hz"
        if "factor" in entry:
            return f"Buckling mode {mode}: load factor {entry['factor']:.3g}"
        return f"Mode {mode}"
    if combination is not None:
        factors = output.load_combinations[combination]
        terms = " + ".join(f"{f:g} × {name}" for name, f in factors.items())
        return f"Load combination: {combination} = {terms}"
    return f"Load case: {case}"


def _default_case(output: AnalysisOutput, case, combination, mode):
    """A mode for a modal or buckling analysis, else the first load case."""
    if case is None and combination is None and mode is None:
        if output.modes:
            mode = 1
        elif output.load_cases:
            case = output.load_cases[0]
        else:
            raise ValueError("The analysis has no load case and no mode")
    return case, combination, mode


def render(
    output: AnalysisOutput,
    case: Optional[str] = None,
    combination: Optional[str] = None,
    mode: Optional[int] = None,
    field: str = "displacement",
    scale: Optional[float] = None,
    supports: bool = True,
    reactions: bool = False,
    loads: bool = False,
    edges: bool = False,
    view: str = "auto",
    title: Optional[str] = None,
    window_size: Tuple[int, int] = (1600, 1000),
    off_screen: bool = False,
) -> "pv.Plotter":
    """Draw one picture of an analysis.

    Args:
        output: The analysis.
        case, combination, mode: What to draw; by default mode 1 of a modal
            or buckling analysis, else the first load case.
        field: ``displacement`` or ``von_mises`` to colour a deformed shape,
            or one of ``DIAGRAMS`` for a section force diagram.
        scale: Deformation scale factor (displacement fields), or length per
            unit force (diagrams, in m per N or N·m); automatic by default.
        supports: Draw the supports.
        reactions: Draw the reactions at the supports (load cases and
            combinations).
        loads: Draw the nodal forces written to the solver.
        edges: Draw the edges of the shell elements.
        view: ``auto`` looks across a plane model and at any other from above
            at an angle; or ``iso``, ``xy``, ``xz``, ``yz``.
        title: First line of the caption; the model's name by default.
        window_size: Size of the picture in pixels.
        off_screen: Render without a window (for screenshots).

    Returns:
        The plotter, to ``show()`` or ``screenshot()``.
    """
    _require_pyvista()
    if field not in FIELDS + DIAGRAMS:
        raise ValueError(f"field must be one of {FIELDS + DIAGRAMS}")
    case, combination, mode = _default_case(output, case, combination, mode)
    if field in DIAGRAMS and mode is not None:
        raise ValueError("A mode shape has no section forces")
    if field == "von_mises" and mode is not None:
        raise ValueError("A mode shape has no stresses")

    points = output.mesh.points
    cells = [cell for group in output.member_cells().values() for cell in group]
    drawn = sorted({n for _, nodes in cells for n in nodes})
    size = _size(points[drawn] if drawn else points)
    segments, triangles, shell_edges = _linear_cells(cells)

    plotter = pv.Plotter(off_screen=off_screen, window_size=list(window_size))
    plotter.set_background("white")
    plotter.enable_anti_aliasing("ssaa")

    caption: List[str] = []
    if field in DIAGRAMS:
        _draw_model(plotter, points, segments, triangles, shell_edges, edges, size)
        caption += _draw_diagrams(
            plotter, output, field, case, combination, scale, size
        )
    else:
        caption += _draw_deformed(
            plotter,
            output,
            points,
            (segments, triangles, shell_edges),
            field,
            (case, combination, mode),
            scale,
            edges,
            size,
        )
    if supports:
        _draw_supports(plotter, output, size)
    if reactions and mode is None:
        caption += _draw_reactions(plotter, output, case, combination, size)
    if loads and mode is None:
        caption += _draw_loads(plotter, output, case, combination, size)

    name = title or output.results.get("model", {}).get("name") or "Model"
    source = output.results.get("run", {}).get("input_file", {}).get("name")
    counts = (
        f"{_count(len(output.members()), 'member')} · "
        f"{_count(len(drawn), 'node')} · {_count(len(cells), 'element')}"
    )
    lines = (
        [
            name + (f" ({source})" if source and source not in name else ""),
            _case_label(case, combination, mode, output),
        ]
        + caption
        + [counts]
    )
    plotter.add_text("\n".join(lines), position="upper_left", font_size=11, color=_TEXT)
    _set_view(plotter, points[drawn] if drawn else points, view)
    return plotter


def _draw_model(plotter, points, segments, triangles, shell_edges, edges, size):
    """The undeformed model in grey, under a diagram."""
    if segments:
        plotter.add_mesh(
            _poly(points, lines=segments),
            color=_MEMBER,
            line_width=3,
            render_lines_as_tubes=True,
        )
    if triangles:
        plotter.add_mesh(_poly(points, faces=triangles), color="#dadce0", opacity=0.45)
        if edges:
            plotter.add_mesh(
                _poly(points, lines=shell_edges), color=_GHOST, line_width=1
            )


def _draw_deformed(
    plotter, output, points, linear, field, what, scale, edges, size
) -> List[str]:
    segments, triangles, shell_edges = linear
    case, combination, mode = what
    displacement = output.displacement(case, combination, mode)
    magnitude = np.linalg.norm(displacement, axis=1)
    largest = float(magnitude.max())
    if scale is None:
        scale = _DEFORMATION_SHARE * size / largest if largest > 0 else 1.0
    moved = points + scale * displacement

    if field == "von_mises":
        values = output.von_mises(case, combination) / 1e6
        bar = "von Mises stress (MPa)"
        caption = [f"Largest von Mises stress {values.max():.3g} MPa"]
    elif mode is not None:
        values = magnitude / largest if largest > 0 else magnitude
        bar = "Mode shape (relative)"
        caption = []
    else:
        values = magnitude * 1e3
        bar = "Displacement (mm)"
        caption = [f"Largest displacement {largest * 1e3:.3g} mm"]
    caption.append(f"Deformation drawn × {scale:,.3g}")

    # The undeformed model, ghosted
    if segments:
        plotter.add_mesh(_poly(points, lines=segments), color=_GHOST, line_width=1)
    if triangles:
        # Only the outline of the shells: all their edges would hide the rest
        outline = _poly(points, faces=triangles).extract_feature_edges(
            boundary_edges=True,
            feature_edges=False,
            manifold_edges=False,
            non_manifold_edges=True,
        )
        plotter.add_mesh(outline, color=_GHOST, line_width=1)

    bar_args = {
        "title": bar,
        "vertical": True,
        "position_x": 0.87,
        "position_y": 0.2,
        "height": 0.6,
        "width": 0.05,
        "color": _TEXT,
        "fmt": "%.3g",
    }
    clim = [0.0, float(values.max()) or 1.0]
    if triangles:
        shells = _poly(moved, faces=triangles)
        shells["value"] = values
        plotter.add_mesh(
            shells,
            scalars="value",
            cmap="viridis",
            clim=clim,
            smooth_shading=True,
            scalar_bar_args=bar_args,
        )
        if edges:
            plotter.add_mesh(
                _poly(moved, lines=shell_edges),
                color="#202124",
                line_width=1,
                opacity=0.3,
            )
    if segments:
        lines = _poly(moved, lines=segments)
        lines["value"] = values
        plotter.add_mesh(
            lines,
            scalars="value",
            cmap="viridis",
            clim=clim,
            line_width=5,
            render_lines_as_tubes=True,
            show_scalar_bar=not triangles,
            scalar_bar_args=bar_args,
        )
    return caption


def _draw_diagrams(plotter, output, field, case, combination, scale, size) -> List[str]:
    key, factor, unit, axis_name = _DIAGRAM_KEYS[field]
    source = (
        "section_force_diagrams_by_combination"
        if combination is not None
        else "section_force_diagrams"
    )
    name = combination if combination is not None else case
    drawn = []
    for member in output.members("curve"):
        diagram = member.get(source, {}).get(name)
        start = output.member_start(member)
        axes = member.get("section_axes", {})
        if not diagram or start is None or key not in diagram:
            continue
        drawn.append(
            (
                member,
                start,
                np.array(axes["x"], dtype=float),
                np.array(axes[axis_name], dtype=float),
                np.array(diagram["distance_m"], dtype=float),
                np.array(diagram[key], dtype=float),
            )
        )
    if not drawn:
        raise ValueError(f"No {field} diagram for {name!r} in results.json")
    largest = max(float(np.abs(values).max()) for *_, values in drawn)
    if scale is None:
        scale = _DIAGRAM_SHARE * size / largest if largest > 0 else 1.0

    labels, label_points = [], []
    # On a large model only the largest of either sign is labelled
    extremes: Dict[str, Tuple[float, np.ndarray]] = {}
    limit = largest * factor
    # One mesh for all the fills and one for all the outlines: a mesh per
    # member takes a minute to draw on a model of a thousand
    fill_points: List[np.ndarray] = []
    fill_values: List[np.ndarray] = []
    quads: List[List[int]] = []
    outlines: List[List[int]] = []
    count = 0
    for member, start, x, across, distance, values in drawn:
        base = start + np.outer(distance, x)
        tip = base + np.outer(values * scale, across)
        n = len(distance)
        quads += [
            [count + i, count + i + 1, count + n + i + 1, count + n + i]
            for i in range(n - 1)
        ]
        outlines.append(list(range(count + n, count + 2 * n)))
        fill_points += [base, tip]
        fill_values += [values, values]
        count += 2 * n
        if len(drawn) <= 16:
            k = int(np.argmax(np.abs(values)))
            if abs(values[k]) > 1e-3 * largest:
                labels.append(f"{values[k] * factor:.3g}")
                label_points.append(tip[k])
        for sign, k in (("+", int(np.argmax(values))), ("-", int(np.argmin(values)))):
            value = float(values[k])
            if (value > 0) == (sign == "+") and abs(value) > abs(
                extremes.get(sign, (0.0, None))[0]
            ):
                extremes[sign] = (value, tip[k])
    fill = _poly(np.vstack(fill_points), faces=quads)
    fill["value"] = np.concatenate(fill_values) * factor
    plotter.add_mesh(
        fill,
        scalars="value",
        cmap="RdBu_r",
        clim=[-limit, limit] if limit > 0 else [-1, 1],
        opacity=0.9,
        scalar_bar_args={
            "title": f"{_DIAGRAM_TITLES[field]} ({unit})",
            "vertical": True,
            "position_x": 0.87,
            "position_y": 0.2,
            "height": 0.6,
            "width": 0.05,
            "color": _TEXT,
            "fmt": "%.3g",
        },
    )
    plotter.add_mesh(
        _poly(np.vstack(fill_points), lines=outlines), color=_TEXT, line_width=1
    )
    if len(drawn) > 16:
        for value, point in extremes.values():
            if abs(value) > 1e-3 * largest:
                labels.append(f"{value * factor:.3g}")
                label_points.append(point)
    if labels:
        plotter.add_point_labels(
            np.array(label_points),
            labels,
            font_size=14,
            text_color=_TEXT,
            shape_opacity=0.6,
            shape_color="white",
            show_points=False,
            always_visible=True,
        )
    return [
        f"{_DIAGRAM_TITLES[field]}, largest {largest * factor:.3g} {unit}, drawn "
        + (
            "on the tension side"
            if field.startswith("Mf")
            else f"on the +{axis_name} side of each section where positive"
        )
    ]


def _draw_supports(plotter, output, size) -> None:
    """A cube where a support holds a rotation, a sphere on a spring, a cone
    where it holds translations only; one mesh of each."""
    radius = _GLYPH_SHARE * size
    found = output.support_nodes()
    rows_of: Dict[str, List[int]] = {"fixed": [], "spring": [], "pinned": []}
    for support in output.results.get("supports", []):
        rows = found.get(support["id"])
        if rows is None:
            continue
        if set(support.get("restrained", [])) & {"rx", "ry", "rz"}:
            rows_of["fixed"] += list(rows)
        elif support.get("springs"):
            rows_of["spring"] += list(rows)
        else:
            rows_of["pinned"] += list(rows)
    glyphs = {
        "fixed": pv.Cube(x_length=2 * radius, y_length=2 * radius, z_length=2 * radius),
        "spring": pv.Sphere(radius=radius),
        "pinned": pv.Cone(direction=(0, 0, 1), height=2 * radius, radius=radius),
    }
    for kind, rows in rows_of.items():
        if rows:
            cloud = pv.PolyData(output.mesh.points[rows] - [0, 0, radius])
            plotter.add_mesh(
                cloud.glyph(geom=glyphs[kind], orient=False, scale=False),
                color=_SUPPORT,
            )


def _arrows(plotter, heads, vectors, length, color, size, labels=None):
    """Arrows of ``length`` per unit of force ending at ``heads``: one mesh
    of shafts and one of heads of a fixed size."""
    heads = np.asarray(heads, dtype=float)
    vectors = np.asarray(vectors, dtype=float)
    norms = np.linalg.norm(vectors, axis=1)
    keep = norms > 1e-6 * norms.max()
    heads, vectors, norms = heads[keep], vectors[keep], norms[keep]
    tails = heads - vectors * length
    tip = 0.02 * size
    # The shafts stop where the cones start
    ends = heads - vectors / norms[:, None] * np.minimum(tip, norms * length)[:, None]
    shafts = _poly(
        np.vstack([tails, ends]),
        lines=[[i, len(tails) + i] for i in range(len(tails))],
    )
    plotter.add_mesh(shafts, color=color, line_width=4)
    cloud = pv.PolyData(ends)
    cloud["direction"] = vectors / norms[:, None]
    cone = pv.Cone(
        center=(tip / 2, 0, 0), direction=(1, 0, 0), height=tip, radius=tip / 3
    )
    plotter.add_mesh(
        cloud.glyph(geom=cone, orient="direction", scale=False), color=color
    )
    if labels:
        plotter.add_point_labels(
            np.array([t for t, _ in labels]),
            [text for _, text in labels],
            font_size=12,
            text_color=color,
            shape_opacity=0.0,
            show_points=False,
            always_visible=True,
        )


def _draw_reactions(plotter, output, case, combination, size) -> List[str]:
    key = "by_load_combination" if combination is not None else "by_load_case"
    name = combination if combination is not None else case
    tails, vectors, labels = [], [], []
    for support in output.results.get("supports", []):
        values = support.get(key, {}).get(name)
        if not values or "fx_N" not in values:
            continue
        vector = np.array([values["fx_N"], values["fy_N"], values["fz_N"]])
        position = np.array(support["position_m"], dtype=float)
        tails.append(position)
        vectors.append(vector)
    if not vectors:
        return []
    largest = max(float(np.linalg.norm(v)) for v in vectors)
    length = _ARROW_SHARE * size / largest if largest > 0 else 0.0
    # Drawn pushing on the structure from outside, ending at the support
    if len(vectors) <= 12:
        labels = [
            (p - v * length, f"{np.linalg.norm(v) / 1e3:.3g} kN")
            for p, v in zip(tails, vectors)
        ]
    # Stopping short of the support's glyph, which would hide the head
    gap = 2.5 * _GLYPH_SHARE * size
    heads = [
        p - v / max(np.linalg.norm(v), 1e-30) * gap for p, v in zip(tails, vectors)
    ]
    if labels:
        labels = [
            (h - v * length, text) for h, v, (_, text) in zip(heads, vectors, labels)
        ]
    _arrows(plotter, heads, vectors, length, _REACTION, size, labels)
    return [f"Reactions (green), largest {largest / 1e3:.3g} kN"]


def _draw_loads(plotter, output, case, combination, size) -> List[str]:
    applied = output.applied_loads(case, combination)
    lines = []
    if applied:
        rows = list(applied)
        vectors = [applied[row] for row in rows]
        largest = max(float(np.linalg.norm(v)) for v in vectors)
        length = _ARROW_SHARE * size / largest if largest > 0 else 0.0
        _arrows(plotter, output.mesh.points[rows], vectors, length, _LOAD, size)
        total = np.sum(vectors, axis=0)
        lines.append(
            f"Nodal loads (red): {_count(len(rows), 'node')}, total {np.linalg.norm(total) / 1e3:,.4g} kN"
        )
    if output.self_weight(case, combination):
        lines.append("Self-weight included (not drawn)")
    return lines


def _set_view(plotter, points: np.ndarray, view: str) -> None:
    if view == "auto":
        flat = _flat_axis(points)
        view = {0: "yz", 1: "xz", 2: "xy"}.get(flat, "iso")
    if view == "iso":
        plotter.view_vector((1.0, -1.6, 0.9), viewup=(0, 0, 1))
    elif view == "xz":
        plotter.view_xz()
        plotter.enable_parallel_projection()
    elif view == "yz":
        plotter.view_yz()
        plotter.enable_parallel_projection()
    elif view == "xy":
        plotter.view_xy()
        plotter.enable_parallel_projection()
    else:
        raise ValueError(f"view must be one of {VIEWS}")
    plotter.reset_camera()
    plotter.camera.zoom(1.15)


def plot(
    directory: str,
    screenshot: Optional[str] = None,
    html: Optional[str] = None,
    **options,
) -> Optional[str]:
    """Draw an analysis on screen, or save the picture.

    Args:
        directory: The output directory of the analysis.
        screenshot: Write a PNG here instead of opening a window.
        html: Write an interactive HTML page here (needs ``trame``).
        **options: Passed to ``render()``.

    Returns:
        The path written, if any.
    """
    output = AnalysisOutput(directory)
    off_screen = bool(screenshot or html)
    plotter = render(output, off_screen=off_screen, **options)
    if screenshot:
        plotter.screenshot(screenshot)
        plotter.close()
        return screenshot
    if html:
        try:
            plotter.export_html(html)
        except ImportError as error:
            raise ImportError(
                "Writing HTML needs trame: pip install trame trame-vtk"
            ) from error
        finally:
            plotter.close()
        return html
    plotter.show()
    return None
