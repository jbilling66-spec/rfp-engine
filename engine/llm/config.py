"""Effective-config assembly (O4, N3): models.yaml + every agent's
config.yaml + a digest of every prompt file. A prompt edit therefore changes
config_digest — prompts are product, and two runs are only comparable when
their digests match.
"""

import datetime
from pathlib import Path

import yaml

from engine.runlog import digest

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"
MODELS_YAML = ROOT / "config" / "models.yaml"
RESEARCH_YAML = ROOT / "config" / "research.yaml"

RESEARCH_MODES = ("full_web", "allowlist", "airgapped")

_PRICE_KEYS = {"input", "output", "cache_read", "cache_write"}


def model_prices(path: Path = MODELS_YAML) -> dict:
    """Load config/models.yaml and validate it loudly (B34(21)): every tier
    model AND fallback must carry a complete four-component price row — a
    fallback call bills at the fallback's rates, and an unpriced model
    reachable by the router is exactly the silent-corruption path B29(a)(2)
    reclassified as BLOCKING. Returns {"pricing_as_of": ..., "tiers": ...,
    "prices": {model_id: {input, output, cache_read, cache_write}}}."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a mapping, got {type(loaded).__name__}")
    for key in ("pricing_as_of", "tiers", "prices"):
        if key not in loaded:
            raise ValueError(f"{path}: missing required key {key!r}")
    valid_until = loaded.get("prices_valid_until")
    if valid_until is not None:
        # Optional dated-pricing marker (B70). Shape-checked here; the
        # refusal itself lives on LiveCaller construction — library code
        # never reads the wall clock (B19(8)), so dry runs stay
        # byte-deterministic while the spend path gets the guard.
        try:
            datetime.date.fromisoformat(str(valid_until))
        except ValueError:
            raise ValueError(
                f"{path}: prices_valid_until must be YYYY-MM-DD, "
                f"got {valid_until!r}") from None
    prices = loaded["prices"]
    reachable = set()
    for tier, entry in loaded["tiers"].items():
        for role in ("model", "fallback"):
            if role not in entry:
                raise ValueError(f"{path}: tier {tier!r} missing {role!r}")
            reachable.add(entry[role])
    unpriced = reachable - set(prices)
    if unpriced:
        raise ValueError(f"{path}: reachable models with no price row: {sorted(unpriced)}")
    for model, row in prices.items():
        if not isinstance(row, dict) or set(row) != _PRICE_KEYS:
            raise ValueError(
                f"{path}: price row for {model!r} must have exactly "
                f"{sorted(_PRICE_KEYS)}, got {sorted(row) if isinstance(row, dict) else row!r}")
        for component, value in row.items():
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(
                    f"{path}: {model}.{component} must be a non-negative number, got {value!r}")
    return loaded


def research_config(path: Path = RESEARCH_YAML) -> dict:
    """Load config/research.yaml. The file is the mode switch (B21): one key,
    validated loudly — a typo'd mode must fail the run, not silently default."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a mapping, got {type(loaded).__name__}")
    unknown = set(loaded) - {"research_mode"}
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    mode = loaded.get("research_mode")
    if mode not in RESEARCH_MODES:
        raise ValueError(
            f"{path}: research_mode must be one of {list(RESEARCH_MODES)}, got {mode!r}")
    return loaded


def effective_config(extra: dict | None = None, *, prompts_dir: Path = PROMPTS_DIR,
                     models_yaml: Path = MODELS_YAML,
                     research_yaml: Path = RESEARCH_YAML) -> dict:
    config: dict = {"models": yaml.safe_load(models_yaml.read_text(encoding="utf-8"))}
    config["research_mode"] = research_config(research_yaml)["research_mode"]
    prompts: dict = {}
    for prompt_file in sorted(prompts_dir.glob("*/prompt.md")):
        agent = prompt_file.parent.name
        entry = {"prompt_digest": digest(prompt_file.read_text(encoding="utf-8"))}
        agent_yaml = prompt_file.parent / "config.yaml"
        if agent_yaml.exists():
            entry["config"] = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
        prompts[agent] = entry
    shared_dir = prompts_dir / "shared"
    if shared_dir.exists():
        for shared in sorted(shared_dir.glob("*.md")):
            prompts[f"shared/{shared.stem}"] = {
                "prompt_digest": digest(shared.read_text(encoding="utf-8"))
            }
    config["prompts"] = prompts
    if extra:
        config.update(extra)
    return config
