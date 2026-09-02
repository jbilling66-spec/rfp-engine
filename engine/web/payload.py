"""Typed payload reads for the web doors (P26a Group A, P3-13).

Route bodies are annotated `payload: dict`, so FastAPI already refuses a
non-object body; the FIELDS inside were read with `.get()` and handed to
regexes, `int()`, and iteration unchecked — a wrong-typed field was a 500,
not a 422. `field()` is the one place a field's shape is checked, and the
422 it raises names the field and the shape it wanted.
"""

from fastapi import HTTPException

_KINDS = {"str": str, "int": int, "dict": dict, "list": list, "bool": bool}
_ARTICLE = {"str": "a string", "int": "an integer", "dict": "an object",
            "list": "a list", "bool": "a boolean"}


def field(payload, name: str, kind: str, *, required: bool = False,
          default=None, choices=None):
    """Read `payload[name]` as `kind` ('str' | 'int' | 'dict' | 'list' |
    'bool'); absent -> `default` (or 422 when required); wrong type -> 422
    naming the field; `choices` -> 422 unless the value is one of them."""
    value = (payload or {}).get(name)
    if value is None:
        if required:
            raise HTTPException(422, f"{name} is required")
        return default
    py = _KINDS[kind]
    if (kind == "int" and isinstance(value, bool)) \
            or not isinstance(value, py):
        raise HTTPException(422, f"{name} must be {_ARTICLE[kind]}")
    if choices is not None and value not in choices:
        raise HTTPException(
            422, f"{name} must be one of {sorted(choices)}")
    return value
