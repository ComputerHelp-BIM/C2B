"""Layer-role profiles.

A profile tells the extractor what each client layer means. Profiles are YAML
files that a drafter can edit. When no profile is given, roles are suggested
automatically from layer names and entity statistics; every guess carries a
confidence so the review workbook shows what needs a human decision.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from .geometry import WALL_LIKE_MIN_LENGTH_MM, WALL_LIKE_MIN_SIDE_RATIO
from .tags import parse_size_from_name

# Roles a layer's geometry or text can play.
ROLES = [
    "BOUNDARY", "ORIGIN",
    "GRID", "COLUMN", "BEAM", "SLAB", "FOOTING", "OPENING", "WALL", "STAIR",
    "SCHEDULE", "NOTE", "TITLE", "DIMENSION", "HATCH_GENERIC", "JOINT",
    "IGNORE", "UNKNOWN",
]
STRUCTURAL_ROLES = {"GRID", "COLUMN", "BEAM", "SLAB", "FOOTING", "OPENING", "WALL", "STAIR"}

# Text on a structural layer is that element's tag.
TEXT_ROLE_FOR = {r: f"{r}_TAG" for r in STRUCTURAL_ROLES}
TEXT_ROLE_FOR.update({"SCHEDULE": "SCHEDULE", "NOTE": "NOTE", "TITLE": "TITLE", "JOINT": "NOTE",
                      "DIMENSION": "IGNORE", "BOUNDARY": "NOTE", "ORIGIN": "IGNORE", "HATCH_GENERIC": "NOTE",
                      "IGNORE": "IGNORE", "UNKNOWN": "NOTE"})

# Ordered (pattern, role, confidence). First match wins. Patterns run on the
# lower-cased layer name.
_RULES: list[tuple[str, str, str]] = [
    (r"^boundary$", "BOUNDARY", "high"),
    (r"^origin$", "ORIGIN", "high"),
    (r"schd|schedule", "SCHEDULE", "high"),
    (r"legend|\bnotes?\b", "NOTE", "high"),
    (r"titl|title", "TITLE", "high"),
    (r"(^|[^a-z])dims?([^a-z]|$)|dimension|anotdim", "DIMENSION", "high"),
    (r"grid|axis|\baxes\b", "GRID", "high"),
    (r"exp(ansion|antion)?[\s._-]*joint|\bej\b|const(ruction)?[\s._-]*joint", "JOINT", "high"),
    (r"cut-?out|opening|shaft|void|duct|sleeve", "OPENING", "high"),
    (r"stair|strs|stp", "STAIR", "medium"),
    (r"\bfnd\b|foot|ftg|foundation|raft|pile|pedestal|\bpcc\b|\bpit\b", "FOOTING", "high"),
    (r"(^|[^a-z])col(umns?|ums?|s|m)?([^a-z]|$)|stub", "COLUMN", "high"),
    (r"beam|^b-\d+x\d+|(^|[^a-z])bm([^a-z]|$)", "BEAM", "high"),
    (r"slab|flor|floor|drop|sunk|ramp", "SLAB", "high"),
    (r"wall|shear|(^|[^a-z])sw([^a-z]|$)|retaining", "WALL", "high"),
    (r"^hat(ch)?$|hatch|solid|fill", "HATCH_GENERIC", "medium"),
    (r"anno|text|\btxt\b", "NOTE", "medium"),
    (r"^defpoints$|viewport|vport|xref|frame|border|cover|furniture|door|window|plumb|elec|hvac", "IGNORE", "medium"),
]

_MODIFIER_RULES: list[tuple[str, str]] = [
    (r"hdln|hidden|hid\b|dash|below|above", "hidden"),
    (r"stop", "stop"),
    (r"start", "start"),
    (r"stub", "stub"),
    (r"fold", "fold"),
    (r"sunk", "sunk"),
    (r"drop", "drop"),
    (r"projection|proj", "projection"),
    (r"non[\s\-_.]*str|non[\s\-_.]*structural|masonry|brick|block\s*work", "non_structural"),
    (r"retaining", "retaining"),
    (r"\braft\b|\bmat\b", "raft"),
    (r"pile\s*cap|pilecap|p\.?\s*cap\b", "pilecap"),
    (r"\bpiles?\b", "pile"),
    (r"\bpcc\b|lean\s*concrete|blinding", "pcc"),
    (r"\bramp", "ramp"),
    (r"\bpit\b", "pit"),
    (r"podium", "podium"),
    (r"hatch|solid|fill", "hatch"),
    (r"iden|(^|[^a-z])no\.?([^a-z]|$)|size|tag|mark|thk|label", "tag_layer"),
]


class LayerRule(BaseModel):
    geometry: str = "UNKNOWN"
    text: str | None = None            # None -> derived from geometry role
    modifiers: list[str] = Field(default_factory=list)
    confidence: str = "high"
    note: str | None = None

    def text_role(self) -> str:
        return self.text or TEXT_ROLE_FOR.get(self.geometry, "NOTE")


class FloorSettings(BaseModel):
    boundary_layer: str = "Boundary"
    origin_layer: str = "Origin"
    label_keywords: list[str] = Field(default_factory=lambda: [
        "level", "lvl", "floor", "plan", "terrace", "foundation", "basement", "podium", "roof",
        "typical", "ground", "plinth", "layout", "storey", "story", "refuge", "stilt", "parking",
    ])
    min_boundary_area_m2: float = 25.0


class Tolerances(BaseModel):
    snap_mm: float = 1.0                  # coordinate snapping for line loops
    duplicate_round_mm: float = 0.1
    ring_close_tol_mm: float = 50.0       # close nearly-closed outlines up to this gap
    column_min_side_mm: float = 100.0
    column_max_side_mm: float = 20000.0
    column_min_area_mm2: float = 10000.0
    column_max_area_mm2: float = 6.0e7
    column_iou_dedupe: float = 0.6
    column_tag_radius_factor: float = 1.5   # x max side of column
    column_tag_radius_min_mm: float = 600.0
    wall_like_min_side_ratio: float = WALL_LIKE_MIN_SIDE_RATIO
    wall_like_min_length_mm: float = WALL_LIKE_MIN_LENGTH_MM
    beam_min_width_mm: float = 100.0
    beam_max_width_mm: float = 1500.0
    beam_min_length_mm: float = 500.0
    beam_stub_min_length_mm: float = 40.0     # brackets / corbels: a 200 wide x 50 long nib is a real member
    beam_min_overlap_mm: float = 300.0
    beam_merge_gap_mm: float = 800.0       # merge collinear edge pieces across crossing beams
    beam_merge_offset_mm: float = 2.0
    beam_tag_buffer_factor: float = 3.5    # x text height
    beam_angle_tol_deg: float = 1.0
    grid_min_length_mm: float = 1500.0
    grid_label_radius_mm: float = 2500.0
    grid_ref_tol_mm: float = 600.0
    slab_min_area_mm2: float = 1.0e6
    footing_min_side_mm: float = 300.0
    opening_min_area_mm2: float = 40000.0
    size_mismatch_tol_mm: float = 26.0
    schedule_row_tol_factor: float = 0.6
    z_tol_mm: float = 0.5
    large_coord_mm: float = 500000.0


class SizeSources(BaseModel):
    """Which witness wins, per element, when the client's tag and their outline disagree.

    ``tag`` takes the tag or schedule and falls back to the outline; ``outline`` measures the
    drawing and keeps the tag for the mark alone. Neither is right for every client -- a firm
    that dimensions carefully wants the outline, one that keeps a maintained schedule wants the
    tag -- so it is a setting, defaulting to the tag as the client's stated intent.
    """

    column: Literal["tag", "outline"] = "tag"
    beam: Literal["tag", "outline"] = "tag"
    slab: Literal["tag", "outline"] = "tag"
    footing: Literal["tag", "outline"] = "tag"


class Profile(BaseModel):
    name: str = "auto"
    description: str | None = None
    units_override: str | None = None
    layers: dict[str, LayerRule] = Field(default_factory=dict)
    floor: FloorSettings = Field(default_factory=FloorSettings)
    tolerances: Tolerances = Field(default_factory=Tolerances)
    size_sources: SizeSources = Field(default_factory=SizeSources)
    explode_blocks: bool = True
    max_block_depth: int = 4

    # ------------------------------------------------------------------
    def rule_for(self, layer: str) -> LayerRule | None:
        if layer in self.layers:
            return self.layers[layer]
        low = layer.lower()
        for name, rule in self.layers.items():
            if name.lower() == low:
                return rule
        return None

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def save(self, path: str | Path) -> None:
        data = self.model_dump(mode="json", exclude_none=True)
        header = (
            "# C2B layer profile. Edit 'geometry' / 'text' roles per layer.\n"
            f"# Roles: {', '.join(ROLES)} (text roles add _TAG, e.g. COLUMN_TAG)\n"
            "# Modifiers: hidden, stop, start, stub, fold, sunk, drop, projection, non_structural, podium, hatch\n"
        )
        Path(path).write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Automatic suggestion
# ---------------------------------------------------------------------------

def suggest_rule(layer: str, entity_counts: dict[str, int] | None = None) -> LayerRule:
    """Suggest a role for one layer from its name (and, as a tie breaker, its content)."""
    low = layer.lower().strip()
    counts = entity_counts or {}
    modifiers = [mod for pat, mod in _MODIFIER_RULES if re.search(pat, low)]
    role, conf, note = "UNKNOWN", "none", None
    for pat, r, c in _RULES:
        if re.search(pat, low):
            role, conf = r, c
            break

    layer_size = parse_size_from_name(layer)
    if role == "UNKNOWN" and layer_size and counts:
        # a layer literally named "500X750" is almost certainly a member outline
        role, conf, note = "COLUMN", "low", "layer name looks like a member size"

    if role == "UNKNOWN":
        n_hatch = counts.get("HATCH", 0)
        n_poly = counts.get("LWPOLYLINE", 0) + counts.get("POLYLINE", 0)
        if n_hatch >= 5 and n_hatch >= 0.5 * max(1, sum(counts.values())):
            role, conf, note = "HATCH_GENERIC", "low", "mostly hatches; used to confirm column outlines"
        elif n_poly >= 5 and sum(counts.values()) == n_poly:
            note = "closed polylines only; could be columns or footings, decide manually"

    # tag-only layers carry no geometry role
    if "tag_layer" in modifiers and role in STRUCTURAL_ROLES:
        modifiers.remove("tag_layer")
    if "hidden" in modifiers and role in STRUCTURAL_ROLES:
        note = (note + "; " if note else "") + "hidden-line content skipped"
    text_role = None
    return LayerRule(geometry=role, text=text_role, modifiers=modifiers, confidence=conf, note=note)


def suggest_profile(layer_stats: dict[str, dict[str, int]], name: str = "auto") -> Profile:
    profile = Profile(name=name)
    for layer, counts in sorted(layer_stats.items()):
        profile.layers[layer] = suggest_rule(layer, counts)
    return profile


def merge_profiles(auto: Profile, user: Profile | None) -> tuple[Profile, dict[str, str]]:
    """Overlay a user profile on the automatic one. Returns the merged profile
    and a map layer -> "profile" | "auto" saying where each rule came from."""
    if user is None:
        return auto, {layer: "auto" for layer in auto.layers}
    merged = user.model_copy(deep=True)
    merged.layers = {}
    sources: dict[str, str] = {}
    for layer, rule in auto.layers.items():
        user_rule = user.rule_for(layer)
        if user_rule is not None:
            merged.layers[layer] = user_rule
            sources[layer] = "profile"
        else:
            merged.layers[layer] = rule
            sources[layer] = "auto"
    # layers only in the user profile (not present in this drawing) are kept for reference
    for layer, rule in user.layers.items():
        if layer not in merged.layers:
            merged.layers[layer] = rule
            sources[layer] = "profile"
    if not merged.name or merged.name == "auto":
        merged.name = user.name
    return merged, sources


def layer_size_hint(layer: str) -> tuple[float, float] | None:
    return parse_size_from_name(layer)


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    return profile.model_dump(mode="json")
