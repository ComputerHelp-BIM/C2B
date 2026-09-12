from c2b.profile import Profile, merge_profiles, suggest_profile, suggest_rule


def test_role_suggestions():
    assert suggest_rule("S-COLS").geometry == "COLUMN"
    assert suggest_rule("COL. SIZE").geometry == "COLUMN"
    assert suggest_rule("01-STR-PODIUM-COLUMN").modifiers == ["podium"]
    assert suggest_rule("BEAM SIZES").geometry == "BEAM"
    assert suggest_rule("B-200x325").geometry == "BEAM"
    assert suggest_rule("S-FND-FOLD").geometry == "FOOTING" and "fold" in suggest_rule("S-FND-FOLD").modifiers
    assert suggest_rule("A-CUTOUT").geometry == "OPENING"
    assert suggest_rule("S-GRID-IDEN").geometry == "GRID"
    assert suggest_rule("G-ANNO-SCHD").geometry == "SCHEDULE"
    assert suggest_rule("S-BEAM-HDLN").geometry == "BEAM" and "hidden" in suggest_rule("S-BEAM-HDLN").modifiers
    assert suggest_rule("S-COLUM_STOP").geometry == "COLUMN" and "stop" in suggest_rule("S-COLUM_STOP").modifiers
    assert suggest_rule("NON STR. RCC WALL").geometry == "WALL" and "non_structural" in suggest_rule("NON STR. RCC WALL").modifiers
    assert suggest_rule("Boundary").geometry == "BOUNDARY" and suggest_rule("Origin").geometry == "ORIGIN"
    assert suggest_rule("A-ANNO-DIMS").geometry == "DIMENSION"
    assert suggest_rule("HAT", {"HATCH": 231}).geometry == "HATCH_GENERIC"
    assert suggest_rule("OTHER", {"LWPOLYLINE": 12}).geometry == "UNKNOWN"


def test_text_role_derivation():
    assert suggest_rule("S-COLS-IDEN").text_role() == "COLUMN_TAG"
    assert suggest_rule("G-ANNO-TEXT").text_role() == "NOTE"


def test_merge_and_roundtrip(tmp_path):
    auto = suggest_profile({"COL": {"LWPOLYLINE": 10}, "MYSTERY": {"LINE": 3}})
    user = Profile(name="client-x")
    user.layers["MYSTERY"] = auto.layers["MYSTERY"].model_copy(update={"geometry": "BEAM", "confidence": "high"})
    merged, sources = merge_profiles(auto, user)
    assert merged.layers["MYSTERY"].geometry == "BEAM" and sources["MYSTERY"] == "profile" and sources["COL"] == "auto"
    path = tmp_path / "p.yaml"
    merged.save(path)
    again = Profile.load(path)
    assert again.layers["MYSTERY"].geometry == "BEAM" and again.name == "client-x"
