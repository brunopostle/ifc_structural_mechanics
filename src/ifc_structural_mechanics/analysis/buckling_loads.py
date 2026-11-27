"""The loads a buckling analysis finds the factors of (bqj).

A buckling factor is what a set of loads has to be multiplied by for the
model to buckle. Load cases that are alternatives (wind or snow) mean nothing
together, so each load combination gets a ``*BUCKLE`` step of its own: each of
its load cases times its factor, self-weight included. A file with no
combinations has a step per load case, and one with no load case either a step
with every load in it, as before.

CalculiX solves each ``*BUCKLE`` step of an input file on its own (measured on
2.23: the same column with its load doubled in a second step has half the
factor), and it adds the loads written to one node in one step.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..utils.error_handling import AnalysisError
from ..utils.messages import warning

# Name of the one set of loads of a model with no load case: every load of it
ALL_LOADS = "Reference loads"
# The load case of --gravity, which no combination includes
GRAVITY = "Gravity"


@dataclass
class BucklingLoadSet:
    """The loads of one ``*BUCKLE`` step.

    Attributes:
        name: What the results under these loads are called: the name of the
            combination or load case.
        kind: ``"load_combination"``, ``"load_case"`` or ``"all_loads"``.
        ifc_guid: The GlobalId of the combination or load case; None for one
            the analysis made itself (``Gravity``, ``Reference loads``).
        factors: ``{load group id: factor}``; empty for ``all_loads``.
        case_factors: ``{load case name: factor}``, as ``results.json`` lists
            a combination's.
        gravity: The factor of the self-weight asked for with ``--gravity``.
    """

    name: str
    kind: str
    ifc_guid: Optional[str] = None
    factors: Dict[str, float] = field(default_factory=dict)
    case_factors: Dict[str, float] = field(default_factory=dict)
    gravity: float = 0.0


def buckling_load_sets(
    model: Any,
    gravity: bool = False,
    combinations: Optional[Sequence[str]] = None,
    load_cases: Optional[Sequence[str]] = None,
) -> Tuple[List[BucklingLoadSet], List[Dict[str, Any]]]:
    """The sets of loads to find the buckling factors of, and warnings.

    Args:
        model: The ``StructuralModel``.
        gravity: Whether self-weight was asked for (``--gravity``): a load
            case of its own, ``Gravity``, which no combination includes.
        combinations: The names of the combinations to analyse; with
            ``load_cases``, only those named are. None for the default:
            every combination, or every load case when there is none.
        load_cases: The names of the load cases to analyse by themselves.

    Returns:
        The sets in the order their steps are written, and the warnings.

    Raises:
        AnalysisError: For a name that is not a combination or load case of
            the file with loads (``E-LOD-009``).
    """
    cases = [g for g in model.load_groups if g.is_load_case and g.has_actions]
    by_id = {g.id: g for g in cases}
    named = _combination_names(model)
    warnings: List[Dict[str, Any]] = []

    if combinations is None and load_cases is None:
        sets: List[BucklingLoadSet] = []
        idle = []
        for combination, name in named:
            found = _combination_set(combination, name, by_id)
            if found is None:
                idle.append(combination)
            else:
                sets.append(found)
        if idle:
            warnings.append(
                warning(
                    "W-LOD-012",
                    f"{len(idle)} load combination(s) include no load case "
                    "with loads and have no buckling factors: "
                    + ", ".join(c.name for c in idle[:3])
                    + (" ..." if len(idle) > 3 else "")
                    + ".",
                    ifc_guids=[c.id for c in idle],
                )
            )
        if not named:
            sets = [_case_set(case) for case in cases]
        if gravity:
            sets.append(BucklingLoadSet(GRAVITY, "load_case", gravity=1.0))
        if not sets:
            sets = [BucklingLoadSet(ALL_LOADS, "all_loads")]
        return _named_apart(sets), warnings

    sets = []
    unknown = []
    for wanted in combinations or ():
        matches = [(c, n) for c, n in named if wanted in (c.name, n)]
        if len(matches) != 1:
            unknown.append(f"combination {wanted!r}")
            continue
        found = _combination_set(*matches[0], by_id)
        if found is None:
            unknown.append(f"combination {wanted!r} (it includes no load case)")
        else:
            sets.append(found)
    for wanted in load_cases or ():
        if wanted == GRAVITY and gravity:
            sets.append(BucklingLoadSet(GRAVITY, "load_case", gravity=1.0))
            continue
        matches = [case for case in cases if case.name == wanted]
        if len(matches) != 1:
            unknown.append(f"load case {wanted!r}")
        else:
            sets.append(_case_set(matches[0]))
    if unknown:
        raise AnalysisError(
            "The buckling analysis was asked for loads the file does not have "
            "as a single load combination or a load case with loads: "
            + ", ".join(unknown)
            + ". Combinations: "
            + (", ".join(n for _, n in named) or "none")
            + "; load cases: "
            + (", ".join(c.name for c in cases) or "none")
            + ".",
            code="E-LOD-009",
        )
    return _named_apart(sets), warnings


def _named_apart(sets: List[BucklingLoadSet]) -> List[BucklingLoadSet]:
    """The sets, each once, with a name of its own: the results under them
    are known by it. A load case of a combination's name is told apart by
    what it is."""
    unique: List[BucklingLoadSet] = []
    for load_set in sets:
        if any(
            (s.kind, s.ifc_guid, s.name)
            == (load_set.kind, load_set.ifc_guid, load_set.name)
            for s in unique
        ):
            continue
        if any(s.name == load_set.name for s in unique):
            load_set.name = f"{load_set.name} ({load_set.kind.replace('_', ' ')})"
        unique.append(load_set)
    return unique


def _combination_names(model: Any) -> List[Tuple[Any, str]]:
    """Each combination with its name in the results: two of one name are
    told apart by their GlobalId, as ``ResultsExporter`` does."""
    named = []
    seen: set = set()
    for combination in getattr(model, "load_combinations", None) or []:
        name = combination.name
        if name in seen:
            name = f"{name} ({combination.id})"
        seen.add(name)
        named.append((combination, name))
    return named


def _combination_set(
    combination: Any, name: str, cases: Dict[str, Any]
) -> Optional[BucklingLoadSet]:
    """A combination's loads, or None when none of its load cases has any."""
    factors: Dict[str, float] = {}
    case_factors: Dict[str, float] = {}
    for group_id, factor in combination.load_groups.items():
        if group_id in cases:
            factors[group_id] = factors.get(group_id, 0.0) + float(factor)
            case = cases[group_id].name
            case_factors[case] = case_factors.get(case, 0.0) + float(factor)
    if not factors:
        return None
    return BucklingLoadSet(
        name, "load_combination", combination.id, factors, case_factors
    )


def _case_set(case: Any) -> BucklingLoadSet:
    return BucklingLoadSet(case.name, "load_case", case.id, {case.id: 1.0})


def governing_set(factors: Sequence[Sequence[Tuple[int, float]]]) -> Optional[int]:
    """The index of the set that buckles first: whose least positive factor
    is the least. None when no set has a positive factor.

    A negative factor is a buckling of the loads reversed, which is not what
    a combination stands for.
    """
    least: Optional[Tuple[float, int]] = None
    for index, modes in enumerate(factors):
        positive = [factor for _, factor in modes if factor > 0.0]
        if positive and (least is None or min(positive) < least[0]):
            least = (min(positive), index)
    return None if least is None else least[1]
