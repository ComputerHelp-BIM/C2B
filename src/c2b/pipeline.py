"""End-to-end extraction: DXF file in, :class:`Project` out."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .diagnostics import DiagnosticsCollector
from .dxfio import Prim, dedupe_prims, iter_prims, layer_stats, load_document, modelspace_extent, read_meta
from .extract.beams import extract_beams
from .extract.columns import extract_columns
from .extract.context import FloorContext
from .extract.footings import extract_footings
from .extract.grids import extract_grids
from .extract.openings import extract_openings, extract_walls
from .extract.slabs import extract_slabs
from .floors import FloorFrame, detect_floors, localise
from .profile import STRUCTURAL_ROLES, LayerRule, Profile, merge_profiles, suggest_profile
from .schedules import ScheduleIndex, parse_schedules
from .schema import DrawingInfo, Floor, LayerMapEntry, Point2, Project, Schedule, ScheduleRow, UnassignedTag
from .tags import parse_tag
from .units import resolve_units

_IMPERIAL_HINT = ("'", '"')


@dataclass
class ExtractionResult:
    project: Project
    frames: list[FloorFrame]
    profile: Profile
    prims: list[Prim]
    meta: object
    scale: float
    roles: dict[str, tuple[str, str]] = field(default_factory=dict)


def build_roles(profile: Profile) -> tuple[dict[str, tuple[str, str]], dict[str, LayerRule]]:
    roles: dict[str, tuple[str, str]] = {}
    rules: dict[str, LayerRule] = {}
    for layer, rule in profile.layers.items():
        roles[layer] = (rule.geometry, rule.text_role())
        rules[layer] = rule
    return roles, rules


def extract(path: str | Path, user_profile: Profile | None = None, units_override: str | None = None) -> ExtractionResult:
    path = Path(path)
    diag = DiagnosticsCollector()
    doc = load_document(path)
    meta = read_meta(doc, path)

    # ---- units -----------------------------------------------------------
    override = units_override or (user_profile.units_override if user_profile else None)
    texts_raw = [e.dxf.text for e in doc.modelspace().query("TEXT")]
    imperial = sum(1 for t in texts_raw if any(ch in t for ch in _IMPERIAL_HINT))
    metric = sum(1 for t in texts_raw if "mm" in t.lower() or "thk" in t.lower())
    units = resolve_units(meta.insunits, modelspace_extent(doc), override, imperial, metric)
    if units.confidence != "high":
        diag.warning("UNITS_GUESSED", f"Units resolved to {units.name} ({units.note}); pass --units to override")
    scale = units.scale_to_mm

    # ---- primitives --------------------------------------------------------
    explode = user_profile.explode_blocks if user_profile else True
    depth = user_profile.max_block_depth if user_profile else 4
    prims, block_log = iter_prims(doc, scale, explode_blocks=explode, max_depth=depth)
    exploded = {b["block"] for b in block_log if not b["block"].startswith("*")}
    if exploded:
        diag.info("BLOCK_EXPLODED", f"{len(block_log)} block reference(s) exploded: {', '.join(sorted(exploded)[:12])}{' ...' if len(exploded) > 12 else ''}")
    prims, dropped = dedupe_prims(prims)
    for layer, n in sorted(dropped.items(), key=lambda kv: -kv[1]):
        (diag.warning if n >= 20 else diag.info)("DUPLICATE_ENTITY", f"{n} duplicate entities removed on layer {layer}", layer=layer)

    tol = (user_profile or Profile()).tolerances
    z_hits = [p for p in prims if p.zmax > tol.z_tol_mm]
    if z_hits:
        worst = max(p.zmax for p in z_hits)
        diag.warning("Z_NONZERO", f"{len(z_hits)} entities have non-zero Z (max {worst:.1f} mm); geometry flattened to Z=0")
    if meta.extmax and max(abs(meta.extmax[0]), abs(meta.extmax[1])) * scale > tol.large_coord_mm:
        diag.info("COORDS_LARGE", f"Drawing coordinates reach {max(abs(meta.extmax[0]), abs(meta.extmax[1])) * scale / 1000:.0f} m from the origin; floor origins make element coordinates local")

    # ---- layer roles -------------------------------------------------------
    stats = layer_stats(prims)
    auto = suggest_profile(stats)
    # honour profile-provided floor layer names in the auto rules
    fs = (user_profile or auto).floor
    for layer in stats:
        if layer.lower() == fs.boundary_layer.lower():
            auto.layers[layer] = LayerRule(geometry="BOUNDARY", confidence="high")
        elif layer.lower() == fs.origin_layer.lower():
            auto.layers[layer] = LayerRule(geometry="ORIGIN", confidence="high")
    profile, sources = merge_profiles(auto, user_profile)
    profile.tolerances = tol
    roles, rules = build_roles(profile)

    layer_map: list[LayerMapEntry] = []
    for layer, counts in sorted(stats.items()):
        rule = profile.layers.get(layer, LayerRule())
        geom_count = sum(v for k, v in counts.items() if k not in ("TEXT", "MTEXT", "ATTRIB", "DIMENSION", "INSERT", "POINT"))
        if rule.geometry == "UNKNOWN" and geom_count > 0:
            (diag.warning if geom_count >= 5 else diag.info)("LAYER_UNMAPPED", f"Layer '{layer}' has {geom_count} geometry entities but no role; assign one in the profile if it is structural", layer=layer)
        elif rule.confidence == "low" and rule.geometry in STRUCTURAL_ROLES | {"HATCH_GENERIC"}:
            diag.info("LAYER_LOW_CONFIDENCE", f"Layer '{layer}' guessed as {rule.geometry} with low confidence ({rule.note or 'name pattern'})", layer=layer)
        if "hidden" in rule.modifiers and rule.geometry in STRUCTURAL_ROLES:
            diag.info("LAYER_HIDDEN", f"Layer '{layer}' ({rule.geometry}) looks like hidden-line content and was skipped", layer=layer)
        layer_map.append(LayerMapEntry(layer=layer, geometry_role=rule.geometry, text_role=rule.text_role(), modifiers=rule.modifiers,
                                       confidence=rule.confidence, source=sources.get(layer, "auto"), entity_counts=counts,
                                       layer_size=list(parse_size_from_layer(layer)) if parse_size_from_layer(layer) else None))

    # ---- floors ------------------------------------------------------------
    frames = detect_floors(prims, roles, profile, diag, meta.layouts)

    # ---- schedules and notes (global) ---------------------------------------
    sched_texts = [p for p in prims if p.kind == "text" and roles.get(p.layer, ("", "NOTE"))[1] == "SCHEDULE"]
    tables = parse_schedules(sched_texts, diag, tol.schedule_row_tol_factor)
    sched_index = ScheduleIndex(tables)

    global_defaults: dict[str, float] = {}
    for p in prims:
        if p.kind != "text" or not p.text:
            continue
        role = roles.get(p.layer, ("", "NOTE"))[1]
        if role not in ("NOTE", "SCHEDULE", "SLAB_TAG", "BEAM_TAG"):
            continue
        parsed = parse_tag(p.text)
        if parsed.note_default:
            what, val = parsed.note_default
            target = next((f for f in frames if f.boundary is not None and f.boundary.contains(p.geom)), None)
            if target is None and len(frames) == 1:
                target = frames[0]
            if target is not None:
                if what == "beam" and target.default_beam_depth is None:
                    target.default_beam_depth = val
                elif what == "slab" and target.default_slab_thickness is None:
                    target.default_slab_thickness = val
                diag.info("DEFAULT_APPLIED", f"Floor {target.id}: note '{parsed.text[:60]}' sets default {what} = {val:.0f} mm", floor_id=target.id, handle=p.handle)
            else:
                global_defaults.setdefault(what, val)
    for f in frames:
        if f.default_beam_depth is None and "beam" in global_defaults:
            f.default_beam_depth = global_defaults["beam"]
        if f.default_slab_thickness is None and "slab" in global_defaults:
            f.default_slab_thickness = global_defaults["slab"]

    # ---- per floor -----------------------------------------------------------
    project = Project(
        drawing=DrawingInfo(
            file=meta.file, dxf_version=meta.dxf_version, insunits=meta.insunits, unit_name=units.name, unit_scale_to_mm=scale,
            unit_source=units.source, unit_confidence=units.confidence, layouts=meta.layouts,
            extents_min=Point2(x=meta.extmin[0] * scale, y=meta.extmin[1] * scale) if meta.extmin else None,
            extents_max=Point2(x=meta.extmax[0] * scale, y=meta.extmax[1] * scale) if meta.extmax else None,
            entity_count=meta.entity_count,
        ),
        profile_name=profile.name, layer_map=layer_map,
    )
    for t in tables:
        project.schedules.append(Schedule(id=t.id, title=t.title, category=t.category, columns=t.columns,
                                          rows=[ScheduleRow(mark=r["mark"], values={k: v for k, v in r.items() if k != "mark"}) for r in t.rows],
                                          source_layer=t.layer))

    for frame in frames:
        localise(frame)
        ctx = FloorContext(frame=frame, roles=roles, rules=rules, tol=tol, diag=diag, schedules=sched_index)
        project.grids.extend(extract_grids(ctx))
        project.columns.extend(extract_columns(ctx))
        project.beams.extend(extract_beams(ctx))
        project.slabs.extend(extract_slabs(ctx))
        project.footings.extend(extract_footings(ctx))
        project.openings.extend(extract_openings(ctx))
        project.walls.extend(extract_walls(ctx))
        ctx.flush_missing_marks()

        # unassigned structural tags
        per_layer: dict[str, list[Prim]] = {}
        for role in ("COLUMN_TAG", "BEAM_TAG", "SLAB_TAG", "FOOTING_TAG", "WALL_TAG", "OPENING_TAG"):
            for t in ctx.texts(role):
                if t.handle in ctx.assigned_tag_handles:
                    continue
                parsed = parse_tag(t.text or "")
                c = t.rep_point()
                if parsed.unparsed:
                    if role in ("OPENING_TAG", "WALL_TAG") or len(t.text or "") > 30:
                        continue   # labels such as LIFT / SHAFT / CUTOUT and prose are not member tags
                    diag.info("TAG_UNPARSED", f"Text '{(t.text or '')[:40]}' on {t.layer} could not be parsed as a tag", floor_id=frame.id, layer=t.layer, handle=t.handle, location=c)
                project.tags_unassigned.append(UnassignedTag(handle=t.handle, layer=t.layer, text=t.text or "", role=role, floor_id=frame.id,
                                                             position=Point2(x=c[0], y=c[1]), parsed=parsed.as_dict()))
                per_layer.setdefault(t.layer, []).append(t)
        hidden_layers = sorted({p.layer for p in frame.prims if p.kind != "text" and "hidden" in rules.get(p.layer, LayerRule()).modifiers and roles.get(p.layer, ("",))[0] in STRUCTURAL_ROLES})
        for layer, items in per_layer.items():
            sample = ", ".join(f"'{(t.text or '')[:20]}'" for t in items[:5])
            hint = f"; hidden-line geometry exists on {', '.join(hidden_layers)} and is skipped, the tags may belong to it" if hidden_layers else ""
            diag.warning("TAG_UNASSIGNED", f"{len(items)} tag(s) on layer {layer} matched no element (e.g. {sample}){hint}", floor_id=frame.id, layer=layer, location=items[0].rep_point())

        project.floors.append(Floor(
            id=frame.id, index=frame.index, name=frame.name, name_source=frame.name_source,
            origin=Point2(x=frame.origin[0], y=frame.origin[1]),
            boundary=[Point2(x=c[0], y=c[1]) for c in list(frame.boundary.exterior.coords)[:-1]] if frame.boundary is not None else [],
            default_beam_depth_mm=frame.default_beam_depth, default_slab_thickness_mm=frame.default_slab_thickness,
        ))

    project.diagnostics = diag.items
    project.recompute_summary()
    return ExtractionResult(project=project, frames=frames, profile=profile, prims=prims, meta=meta, scale=scale, roles=roles)


def parse_size_from_layer(layer: str):
    from .tags import parse_size_from_name
    return parse_size_from_name(layer)


def suggest_profile_for_file(path: str | Path, units_override: str | None = None) -> Profile:
    """Auto-suggest a profile for a drawing (blocks exploded so nested layers are seen)."""
    doc = load_document(path)
    meta = read_meta(doc, path)
    units = resolve_units(meta.insunits, modelspace_extent(doc), units_override)
    prims, _ = iter_prims(doc, units.scale_to_mm)
    profile = suggest_profile(layer_stats(prims), name=Path(path).stem)
    profile.description = f"Auto-suggested by c2b {__version__} from {meta.file}. Review every 'low'/'none' confidence entry."
    return profile
