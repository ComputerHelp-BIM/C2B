"""Tag to element association.

A tag belongs to the element whose outline contains its text centre. Otherwise
candidates within a radius (element size and text height dependent) are ranked
by distance, with a penalty for text not running parallel to a beam, and
assigned greedily while preferring elements that have no tag yet.

Greedy order is not the same as sharing the tags out well, so an element the
greedy starved is then fed by re-homing a tag a neighbour can spare -- the
augmenting step of bipartite matching, run only for the starved so that every
assignment the greedy got right is left alone. A tag written inside an element
is never taken from it.

Two clean-up passes follow: tags are rebalanced from over-tagged elements to
untagged neighbours, and still-orphaned tags get a relaxed-radius second chance
limited to untagged (and, for beams, parallel) elements. Element/tag pairs are
logged so the reviewer can see why a size was chosen.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

from ..dxfio import Prim
from ..geometry import angle_diff_deg, text_box
from ..tags import ParsedTag, parse_size_from_name, parse_tag


@dataclass
class TagCand:
    prim: Prim
    parsed: ParsedTag
    center: tuple[float, float]
    rotation: float
    height: float
    box: Polygon
    prims: list[Prim] = None  # type: ignore[assignment]   # all texts making up this tag (mark + size groups)

    def __post_init__(self) -> None:
        if self.prims is None:
            self.prims = [self.prim]

    @property
    def layer_size(self) -> tuple[float, float] | None:
        """Size encoded in the tag's own layer name (e.g. text 'B6' on layer 'B-200x325')."""
        for p in self.prims:
            ls = parse_size_from_name(p.layer)
            if ls:
                return ls
        return None


def tag_kind(tag: TagCand) -> str:
    """'size' for texts carrying a size/thickness, 'mark' for a bare mark, else 'other'.

    Elements commonly carry one text of each kind (mark on one layer, size on another),
    so "does this element already have a tag" must be asked per kind.
    """
    if tag.parsed.has_size:
        return "size"
    if tag.parsed.mark:
        return "mark"
    return "other"


def make_tag_cands(texts: list[Prim], group_factor: float = 3.0) -> list[TagCand]:
    """Build tag candidates, pairing a bare mark text with the size text stacked next to it.

    Many drawings put the mark on one layer and the size on another, one above the
    other. Treating the pair as one tag removes the ambiguity of assigning them
    separately to neighbouring members.
    """
    out: list[TagCand] = []
    for t in texts:
        parsed = parse_tag(t.text or "")
        c = t.rep_point()
        w = t.extra.get("box_w", t.text_height * 0.7 * len(t.text or ""))
        h = t.extra.get("box_h", t.text_height)
        out.append(TagCand(t, parsed, c, t.rotation % 180.0, t.text_height, text_box(c, w, h, t.rotation)))
    if group_factor <= 0:
        return out
    marks = [i for i, t in enumerate(out) if tag_kind(t) == "mark"]
    sizes = [i for i, t in enumerate(out) if tag_kind(t) == "size" and not out[i].parsed.mark]
    if not marks or not sizes:
        return out
    size_pts = [Point(out[i].center) for i in sizes]
    tree = STRtree(size_pts)
    pairs = []
    for mi in marks:
        m = out[mi]
        limit = group_factor * m.height
        for k in tree.query(Point(m.center).buffer(limit), predicate="intersects"):
            si = sizes[int(k)]
            sz = out[si]
            if angle_diff_deg(m.rotation, sz.rotation) > 5.0:
                continue
            d = Point(m.center).distance(Point(sz.center))
            if d <= group_factor * max(m.height, sz.height):
                pairs.append((d, mi, si))
    pairs.sort()
    used: set[int] = set()
    grouped: dict[int, int] = {}
    for _d, mi, si in pairs:
        if mi in used or si in used:
            continue
        used.add(mi)
        used.add(si)
        grouped[mi] = si
    if not grouped:
        return out
    result: list[TagCand] = []
    for i, t in enumerate(out):
        if i in grouped:
            sz = out[grouped[i]]
            merged, _ = merge_parsed([t, sz])
            merged.raw, merged.text = f"{t.parsed.raw} | {sz.parsed.raw}", f"{t.parsed.text} | {sz.parsed.text}"
            cx, cy = (t.center[0] + sz.center[0]) / 2, (t.center[1] + sz.center[1]) / 2
            result.append(TagCand(t.prim, merged, (cx, cy), t.rotation, max(t.height, sz.height), t.box.union(sz.box).envelope, prims=[t.prim, sz.prim]))
        elif i in used:
            continue   # absorbed into a group
        else:
            result.append(t)
    return result


#: How far a re-homing chain may run before it is abandoned; real chains are one or two long.
_AUGMENT_MAX_DEPTH = 6


def associate_tags(
    polys: list[Polygon],
    tags: list[TagCand],
    radius_fn: Callable[[int, TagCand], float],
    angles: list[float] | None = None,
    parallel_tol_deg: float = 5.0,
    parallel_penalty: float = 2.5,
    relaxed_factor: float = 2.5,
    max_search_mm: float = 6000.0,
    size_match_fn: Callable[[int, TagCand], bool | None] | None = None,
    size_mismatch_penalty: float = 3.0,
) -> tuple[dict[int, list[int]], list[int]]:
    """Return (element_index -> [tag indices], unassigned tag indices).

    ``size_match_fn`` answers whether a tag's stated size matches an element as drawn: True it
    does, False it states one that does not, None it states none. Where two members stand close
    enough to argue over a tag, the size the client wrote on it settles which of them it names --
    a far better witness than which outline the text happens to sit a few millimetres nearer.
    """
    assigned: dict[int, list[int]] = {}
    tag_owner: dict[int, int] = {}
    if not polys:
        return assigned, list(range(len(tags)))
    tree = STRtree(polys)
    kinds = [tag_kind(t) for t in tags]

    def has_kind(i: int, kind: str) -> bool:
        return any(kinds[k] == kind for k in assigned.get(i, []))

    def n_kind(i: int, kind: str) -> int:
        return sum(1 for k in assigned.get(i, []) if kinds[k] == kind)

    def is_parallel(i: int, tag: TagCand) -> bool:
        return angles is None or angle_diff_deg(angles[i], tag.rotation) <= parallel_tol_deg

    # pass 1: containment
    pairs: list[tuple[float, int, int, bool]] = []       # (score, tag, elem, parallel)
    for ti, tag in enumerate(tags):
        pt = Point(tag.center)
        hits = tree.query(pt, predicate="within")
        if len(hits):
            best = min((int(i) for i in hits), key=lambda i: polys[i].area)
            assigned.setdefault(best, []).append(ti)
            tag_owner[ti] = best
            continue
        for i in (int(k) for k in tree.query(pt.buffer(max_search_mm), predicate="intersects")):
            d = polys[i].distance(pt)
            if d > radius_fn(i, tag):
                continue
            par = is_parallel(i, tag)
            penalty = 1.0 if par else parallel_penalty
            if size_match_fn is not None and size_match_fn(i, tag) is False:
                penalty *= size_mismatch_penalty
            pairs.append((d * penalty, ti, i, par))
    pairs.sort(key=lambda p: (p[0], p[1], p[2]))

    # pass 2: greedy, preferring elements without a tag of the same kind
    for _score, ti, i, _par in pairs:
        if ti in tag_owner or has_kind(i, kinds[ti]):
            continue
        assigned.setdefault(i, []).append(ti)
        tag_owner[ti] = i
    # pass 3: remaining tags go to their best candidate anyway
    for _score, ti, i, _par in pairs:
        if ti in tag_owner:
            continue
        assigned.setdefault(i, []).append(ti)
        tag_owner[ti] = i

    # pass 3b: feed an element the greedy starved, by re-homing a tag its neighbour can spare.
    # Taking the pairs in order of distance is not the same as sharing them out well: where two
    # legs of a wall stand close, the tag that is one leg's only option goes to the neighbour
    # that had another, and the first leg ends with nothing. That accounted for 71 of Test17's
    # 108 unmarked columns. This is the augmenting step of bipartite matching, run only for the
    # starved, so every assignment the greedy got right is left alone.
    cands_by_elem: dict[tuple[int, str], list[tuple[float, int]]] = {}
    for score, ti, i, _par in pairs:
        cands_by_elem.setdefault((i, kinds[ti]), []).append((score, ti))
    for key in cands_by_elem:
        cands_by_elem[key].sort()

    def augment(i: int, kind: str, seen: set[int], depth: int = 0) -> bool:
        if depth > _AUGMENT_MAX_DEPTH:
            return False
        for _score, ti in cands_by_elem.get((i, kind), []):
            if ti in seen:
                continue
            seen.add(ti)
            j = tag_owner.get(ti)
            if j is not None and polys[j].contains(Point(tags[ti].center)):
                continue          # a tag written inside its element belongs to it; never stolen
            # j can let this one go if it keeps another of the kind, or can find a replacement
            if j is None or n_kind(j, kind) > 1 or (j != i and augment(j, kind, seen, depth + 1)):
                if j is not None:
                    assigned[j].remove(ti)
                assigned.setdefault(i, []).append(ti)
                tag_owner[ti] = i
                return True
        return False

    for (i, kind) in sorted(cands_by_elem):
        if not has_kind(i, kind):
            augment(i, kind, set())

    # pass 4: rebalance duplicates of one kind onto neighbours lacking that kind
    by_tag_elems: dict[int, list[tuple[float, int]]] = {}
    for score, ti, i, _par in pairs:
        by_tag_elems.setdefault(ti, []).append((score, i))
    for i, tis in list(assigned.items()):
        for ti in list(tis):
            kind = kinds[ti]
            if n_kind(i, kind) < 2 or polys[i].contains(Point(tags[ti].center)):
                continue
            for _score, j in sorted(by_tag_elems.get(ti, [])):
                if j != i and not has_kind(j, kind):
                    assigned[i].remove(ti)
                    assigned.setdefault(j, []).append(ti)
                    tag_owner[ti] = j
                    break

    # pass 5: relaxed radius for orphans, only to elements lacking that kind.
    #
    # Running along the member is how a beam label is usually written, so it is preferred -- but
    # it is not required here, because this pass is the last chance for a tag nobody claimed to
    # reach an element with no tag of its kind, and both sides are otherwise lost. Test10's
    # drafter writes "B_300 X 600" horizontally beside vertical beams: 71 beams of 271 came out
    # with no depth and were dropped from the Revit model, for the orientation of the lettering.
    for ti, tag in enumerate(tags):
        if ti in tag_owner:
            continue
        pt = Point(tag.center)
        best = None                       # (not parallel, distance, index): parallel wins a tie
        for i in (int(k) for k in tree.query(pt.buffer(max_search_mm), predicate="intersects")):
            if has_kind(i, kinds[ti]):
                continue
            d = polys[i].distance(pt)
            if d > relaxed_factor * radius_fn(i, tag):
                continue
            here = (not is_parallel(i, tag), d, i)
            if best is None or here < best:
                best = here
        if best is not None:
            assigned.setdefault(best[2], []).append(ti)
            tag_owner[ti] = best[2]

    unassigned = [ti for ti in range(len(tags)) if ti not in tag_owner]
    return assigned, unassigned


def merge_parsed(tags: list[TagCand]) -> tuple[ParsedTag, list[tuple[float | None, float | None, float | None]]]:
    """Combine several tags of one element. Returns a merged view and the list of distinct sizes seen.

    A size encoded in a tag's own layer name is used when no tag text carries a size.
    """
    merged = ParsedTag(raw="; ".join(t.parsed.raw for t in tags), text="; ".join(t.parsed.text for t in tags))
    sizes: list[tuple[float | None, float | None, float | None]] = []
    for t in tags:
        p = t.parsed
        if merged.mark is None and p.mark:
            merged.mark = p.mark
            merged.category_hint = p.category_hint
        for m in p.marks:
            if m not in merged.marks:
                merged.marks.append(m)
        if p.width_mm is not None or p.diameter_mm is not None:
            key = (p.width_mm, p.depth_mm, p.diameter_mm)
            if key not in sizes:
                sizes.append(key)
            if merged.width_mm is None and p.width_mm is not None:
                merged.width_mm, merged.depth_mm, merged.depth_alt_mm = p.width_mm, p.depth_mm, p.depth_alt_mm
            if merged.diameter_mm is None and p.diameter_mm is not None:
                merged.diameter_mm = p.diameter_mm
        if merged.thickness_mm is None and p.thickness_mm is not None:
            merged.thickness_mm = p.thickness_mm
        if merged.fold_mm is None and p.fold_mm is not None:
            merged.fold_mm = p.fold_mm
        if merged.sunk_mm is None and p.sunk_mm is not None:
            merged.sunk_mm = p.sunk_mm
        merged.inverted = merged.inverted or p.inverted
        if merged.category_hint is None and p.category_hint:
            merged.category_hint = p.category_hint
    if merged.width_mm is None and merged.diameter_mm is None:
        for t in tags:
            ls = t.layer_size
            if ls:
                merged.width_mm, merged.depth_mm = ls
                sizes.append((ls[0], ls[1], None))
                merged.raw += f" [layer {t.prim.layer}]"
                break
    return merged, sizes
