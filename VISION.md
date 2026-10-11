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

Individual tasks and bugs are tracked in the `bd` (beads) issue database, not
here. This section states what each phase is for and where it stands; run
`bd list --status=open` for the work itself.

### Phase 1 — Reliable core analysis *(in progress)*

The pipeline runs end to end and single members agree with beam theory
(`docs/validation_report.md`). It is not yet reliable for whole buildings.

What holds it back:

- **Stresses and torsion of non-rectangular sections.** Every profile other
  than a solid rectangle is analysed as a rectangle of the same axial, bending
  and shear stiffness on a native beam element, so any model runs on stock
  CalculiX. Tubes, boxes and round bars also have their torsional stiffness,
  paid for in shear stiffness; open sections are tens of times too stiff in
  torsion, and solid rectangles up to 18%.
- **Multi-member models.** One mixed model (`structure_01`) now agrees with an
  independent Code_Aster result to 2%, point by point. `building_01` and
  `building_02` both solve with reactions that match their loads; neither has
  a reference. `building_02` now gives plausible deflections and correct
  reactions, but it has no reference and is too large to refine on a small
  machine.
- **Releases.** Skew supports are not modelled, and end releases on open
  sections are full pins.
- **Input the tool cannot handle.** It now stops, naming the entity, rather
  than substitute a default; what it does not support at all (applied
  moments, surface supports, loads that vary along a
  member) is listed in the README.
- **Validation coverage.** Pinned supports, open sections, area loads and a
  torsion frame now have benchmarks; a multi-storey frame does not.

**Done when**: every example model either agrees with an independent reference
or fails with a message that names the cause.

### Phase 2 — JSON results output *(partially done)*

`results.json` exists, is keyed to IFC GlobalIds, carries per-load-case
displacement and stress envelopes, and has a `status` field driven by optional
limits. The schema is documented in `export/results_exporter.py`.

Displacement and stress are attributed to every member, beams included, through
the element connectivity of the solver's result file, and reactions are given
per load case.

Every beam and column also carries the envelope of its section forces (N, two
shears, two moments, torque), the largest normal stress they give in its real
section, and a utilisation ratio where the material has a yield stress. The
forces are integrated from the solver's stresses over each cross-section,
because CalculiX only writes them itself in a mode that loses shell bending
stress.

The same forces are given along each member, signed, as diagrams in axes the
file states. Results too large to be believed (a member distorting by more
than 1/100 of its size, a displacement over 5% of the model) raise a warning
that names the load case and the member.

Missing: checks beyond normal stress (shear, buckling, concrete), utilisation
for shells, per-node displacement detail, and a CLI flag for limits.

**Done when**: `ifc-analysis analyze model.ifc --output ./results` writes a
`results.json` from which a script can find the most-utilised member by
GlobalId, beams included.

### Phase 3 — Bonsai wrapper *(separate repo, not started)*

A Bonsai panel that runs this library on the active IFC file and paints the
results in the viewport: per-member colour overlay, load case switcher, results
table with click-to-select, displacement scale.

**Done when**: an engineer can open an IFC structural model in Bonsai, click
"Run Analysis", and see stress colours on the members within the same session.

### Phase 4 — BCF output *(separate package, not started)*

A BCF writer that turns `results.json` plus the IFC file into one issue per
member over a threshold, with a viewpoint on the element.

### Phase 5 — PDF report *(separate package, not started)*

A generated summary from `results.json`: model overview, load cases, per-member
table, reactions, pass/fail.

### Phase 6 — Documentation *(not started)*

Four documents for four audiences: a user guide for engineers authoring IFC
structural models, an API and JSON schema reference, an architecture guide for
contributors, and the validation report.

**Done when**: a structural engineer unfamiliar with FEA can set up an IFC
model, run the analysis, and interpret the results using only the
documentation.
