# Vision

## What this tool is

A **backend analysis engine** that takes structural analysis tasks defined in IFC files,
runs finite element analysis, and returns machine-readable results keyed to the original
IFC entities.

The user's authoring tool (typically Bonsai) holds the structural model. This library is
invoked as a service — via CLI or Python API — and hands results back. It does not
provide a UI and does not own the model.

## Relationship to other tools

Bonsai has an experimental structural analysis pipeline based on Code Aster. This library
uses CalculiX and has a different focus: it treats the IFC structural schema as the
authoritative input (rather than deriving a structural model from the architectural
geometry), and its primary output is machine-readable results keyed to IFC GlobalIds for
downstream consumption. The two tools may be complementary rather than competing.

## What problem it solves

IFC has a well-developed structural analysis schema (`IfcStructuralAnalysisModel`,
`IfcStructuralCurveMember`, `IfcStructuralLoadCase`, etc.) but no open-source tool that
reliably runs that model through a real FEA solver. Engineers who author IFC-native
structural models have no way to verify them without exporting to a proprietary format.

This tool closes that gap: **if you can describe it in IFC, you can analyse it here**.

## Output philosophy

### Primary output: JSON results keyed to IFC GlobalIds

Every result — displacement, stress, reaction force — is linked back to its originating
IFC entity by GlobalId. This is what makes the output composable: any downstream tool
that knows the IFC model can consume and display the results without understanding FEA
formats.

The JSON schema has two levels:

- **Summary**: per-member envelope values (max displacement, max stress, reaction
  resultant), plus a `status` field (`ok` / `warning` / `fail`) against user-supplied
  limits. Compact enough to drive a table view or colour overlay.
- **Detail**: per-node and per-element values, per load case. Needed for spatial
  visualisation (colour gradients, displacement arrows).

Both levels are keyed to IFC GlobalIds. Load case results are labelled by
`IfcStructuralLoadCase.Name`, not by step index.

Units are declared explicitly in the JSON (metres, Pascals, Newtons). The IFC model's
unit system is normalised to SI before analysis; the JSON reflects SI values.

### Native IFC principle

Results are **never embedded in the source IFC file**. The IFC file is the design intent;
results are derived artifacts. They are regeneratable, version independently of the model,
and can be enormous. Storing them in the IFC file would conflate two things that change
at different rates and for different reasons.

`IfcStructuralResultGroup` and related entities are not used as output format.

### Secondary outputs: BCF and PDF (separate modules)

BCF (BIM Collaboration Format) is the right channel for flagging structural issues back
into a BIM workflow. A BCF issue can point at a specific `IfcStructuralCurveMember` by
GlobalId, include a rendered image of the stress distribution, and be consumed by any
BIM tool without modifying the source IFC. Over-stressed members, excessive deflection,
near-mechanism warnings — these all map naturally to BCF issues.

A PDF report provides a human-readable summary: model overview, load cases, per-member
results table, reaction summary, pass/fail status.

Both are **separate, lightweight modules** that consume only the JSON output. They have
no dependency on the analysis pipeline and can be developed, versioned, and distributed
independently. Neither belongs in this library.

## Intended primary UI: Bonsai wrapper *(separate repo)*

The analysis is initiated from within Bonsai, which already holds the IFC model and its
geometry. A wrapper panel:

1. Calls this library (as subprocess or Python import) with the active IFC file
2. Receives JSON results
3. Paints a colour overlay on structural members in the Blender viewport (green→red by
   utilisation ratio, displacement arrows at nodes, switchable by load case)
4. Provides a panel/table to sort and filter members by result value, click-to-select
   the IFC element

The overlay is temporary session state — the IFC file is never modified. When the model
changes, the user reruns the analysis. This is the correct Native IFC pattern.

The existing PyVista visualiser (`visualize.py`) is a developer/debugging tool and is not
the production UI.

## Architecture boundaries

```
IFC file
   │
   ▼
ifc_structural_mechanics        ← this library
   │  extracts structural model from IFC
   │  meshes with Gmsh
   │  writes and runs CalculiX
   │  parses and traces results back to IFC GlobalIds
   │
   ▼
results.json                    ← primary output (GlobalId-keyed)
   │
   ├──▶ Bonsai wrapper          ← viewport overlay, table view (separate repo)
   ├──▶ bcf-writer module       ← BCF issues with rendered images (separate package)
   └──▶ pdf-writer module       ← summary report (separate package)
```

The library has no UI dependencies. The Bonsai wrapper, BCF writer, and PDF writer have
no FEA knowledge — they only consume the JSON schema.

## Milestones

### Phase 1 — Reliable core analysis *(largely complete)*

The most important remaining item is full section coverage for linear members.

**Section properties via `SECTION=GENERAL`**

CalculiX B31 beam elements accept `SECTION=GENERAL`, where cross-sectional properties
are supplied directly: area A, moments of inertia I11/I22, product of inertia I12, and
St. Venant torsional constant IT. This unlocks the full range of IFC profile types
without any approximation:

- `IfcIShapeProfileDef`, `IfcTShapeProfileDef`, `IfcLShapeProfileDef`,
  `IfcCShapeProfileDef`, `IfcUShapeProfileDef`: computed analytically from explicit
  geometric dimensions in the IFC entity
- `IfcArbitraryClosedProfileDef`: computed numerically from polygon coordinates
  (shoelace formula for area, numerical integration for Iy/Iz/Iyz)
- Property sets (`Pset_SectionCommon` etc.): pre-computed values stored in the IFC
  file can be used as a fallback or override

`SECTION=GENERAL` does not produce per-fibre stresses at the CalculiX level — CalculiX
outputs section forces and moments (N, My, Mz, Vy, Vz, T). Utilisation ratios
(σ = M/I × y_max) are computed in the JSON output layer using the same section
properties already extracted from IFC. This is sufficient for code-checking.

The existing RECT/CIRC/PIPE/BOX paths are retained where CalculiX's built-in section
integration is preferred.

**Other known limitations:**

- **Connection topology**: connections are resolved by geometric proximity rather than
  `IfcRelConnectsStructuralMember` relationship data. Closely spaced but unconnected
  members can be incorrectly joined.
- **Intermediate supports**: supports at intermediate points on a beam (not at endpoints)
  may be silently omitted if Gmsh does not place a node there.
- **Partial end-releases**: only full pins (all rotational DOFs released) are modelled.
  Per-DOF partial releases are out of scope.

### Phase 2 — JSON results output

- [ ] Define and document the JSON schema (summary + detail levels, unit declarations,
  status fields, section force/moment output per member)
- [ ] Implement `ResultsExporter` that consumes `StructuralModel` post-analysis and
  writes JSON
- [ ] Load case axis in results (per-case values, not just global envelope)
- [ ] Utilisation ratio computation from section forces + section properties
- [ ] `status` field driven by user-supplied limit parameters (CLI flags or config file)
- [ ] Integration tests asserting JSON output for all example models

**Done when**: `ifc-analysis analyze model.ifc --output ./results` writes `results.json`
that a script can consume to find the most-stressed member by GlobalId.

### Phase 3 — Bonsai wrapper *(separate repo)*

- [ ] Bonsai panel that invokes this library and receives JSON
- [ ] Per-member colour overlay in the Blender viewport
- [ ] Load case switcher
- [ ] Results table with click-to-select
- [ ] Displacement scale slider

**Done when**: an engineer can open an IFC structural model in Bonsai, click "Run
Analysis", and see stress colours on the members within the same session.

### Phase 4 — BCF output module *(separate package)*

- [ ] BCF 2.1 writer that consumes `results.json` and an IFC file
- [ ] One BCF issue per member exceeding a threshold, with viewpoint pointing at the
  element
- [ ] Rendered stress/displacement image attached to each issue
- [ ] CLI: `ifc-analysis-to-bcf results.json model.ifc --output issues.bcf`

### Phase 5 — PDF report module *(separate package)*

- [ ] Auto-generated PDF from `results.json`: model overview, load case summary,
  per-member table, reaction table, pass/fail status
- [ ] CLI: `ifc-analysis-to-pdf results.json --output report.pdf`

### Phase 6 — Full technical documentation

The library is only as useful as its documentation. Target audiences are different and
need separate documents:

- **User guide**: how to author an IFC structural model that this tool can analyse —
  which IFC entities are required, which profile types are supported, how to set up load
  cases, what the output means. Aimed at structural engineers using Bonsai.
- **API reference**: auto-generated from docstrings (Sphinx or MkDocs). Covers the
  public Python API (`run_enhanced_analysis`, `StructuralModel`, `ResultsExporter`) and
  the JSON results schema. Aimed at developers building wrappers or consuming output.
- **Architecture guide**: the pipeline from IFC → domain model → Gmsh → CalculiX →
  JSON, traceability chain, extension points (adding new member types, section types,
  load types). Aimed at contributors.
- **Validation report**: for each supported model type, the analytical reference solution
  and the library's result, confirming accuracy bounds. Aimed at engineers assessing
  fitness for use.

**Done when**: a structural engineer unfamiliar with FEA can set up an IFC model, run
the analysis, and interpret the results using only the documentation — without reading
source code.
