"""Path containment (M-20, P26b-3): a caller-supplied name resolves INSIDE
a root or refuses — the guard five call sites carried inline
(engine/workspace/pursuit.py's shape), lifted once. The older copies
migrate here on the next touch of each file (B119 §4)."""

from pathlib import Path

from engine.contracts.validate import ContractError


def within(root: Path, name: str) -> Path:
    """`root / name`, resolved, proven to sit under `root` — a `..`, an
    absolute name or a symlink out of the root is a typed refusal
    naming the root, never a read somewhere else."""
    root = Path(root)
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ContractError(f"{name!r} escapes {root}")
    return path
