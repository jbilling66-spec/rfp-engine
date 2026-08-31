"""Two-path tripwire (C8) — the diff half of the §A2.3 fabrication probe,
extracted from the gate's inlined driver so production intake (C10) and the
gate share one implementation.

Semantics split (B51/B57): the DIFF is the tripwire — any cell where the
deterministic and VLM extractions disagree is an unattributable divergence.
The gate, holding a labeled answer key, additionally ATTRIBUTES divergences
(fabricated_cells) and can kill; production has no key, so a finding here
never scores — it code-forces mandatory review (C10). The VLM view is
consulted and discarded: it never enters any production artifact.
"""

from engine.extraction.gate import diff_cell_grids


def two_path_review(det_grids: list, vlm_grids: list) -> dict:
    """Diff every deterministic table against its VLM counterpart for one
    document. Grids arrive in worker-view shape ({"grid": [[str]], ...});
    a table the VLM path lacks diffs against empty — absence is a finding,
    not a skip. Empty findings == the two paths agree."""
    findings = []
    tables_diffed = 0
    for i, table in enumerate(det_grids):
        vlm_grid = vlm_grids[i]["grid"] if i < len(vlm_grids) else []
        tables_diffed += 1
        for d in diff_cell_grids(table["grid"], vlm_grid):
            findings.append({"table": i, **d})
    return {"tables_diffed": tables_diffed, "findings": findings}
