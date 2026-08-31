"""Picture classification, consumed (C11 close of B51's "picture
classification ships in P12").

The gate has computed docling's figure classes since C5
(do_picture_classification=True); until now nothing READ them. This maps
classified figures to short flag slugs for the intake adapter: a logo or
signature in a buyer document is layout the drafting path must not treat
as content, and on any future firm-authored source it is identity. Flags
ride ExtractedDoc.extraction_flags into the extraction artifact and the
mandatory-review force (C10 carriers).

Only identity-bearing classes flag — charts, maps, screenshots and other
figure classes are ordinary document furniture."""

IDENTITY_CLASSES = {"logo", "signature"}
CONFIDENCE_FLOOR = 0.5


def media_findings(figures: list) -> list[str]:
    """Sorted, deduplicated flag slugs (e.g. ["figure_logo"]) from a
    view's figures. Accepts FigureView objects or their dict form."""
    found = set()
    for fig in figures:
        classes = fig.classes if hasattr(fig, "classes") else fig.get("classes", [])
        for cls in classes:
            label = str(cls.get("label", "")).lower()
            if label in IDENTITY_CLASSES and cls.get("confidence", 0) >= CONFIDENCE_FLOOR:
                found.add(f"figure_{label}")
    return sorted(found)
