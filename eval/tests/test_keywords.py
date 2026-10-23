from cmeval.adapters.keywords import MAX_KEYWORDS, extract_keywords


def test_backticks_come_first_then_identifiers_then_words():
    kws = extract_keywords("Disabled users stay logged in after `revoke_session()` on SessionManager")
    assert kws[0] == "revoke_session"  # backtick span, () removed
    assert kws.index("sessionmanager") < kws.index("disabled")  # identifier before plain word
    assert "users" in kws and "logged" in kws


def test_identifier_shapes():
    kws = extract_keywords("calls get_user and getUserById and HTTPAdapter and parse(x) and db.sessions.delete")
    for kw in ["get_user", "getuserbyid", "httpadapter", "db.sessions.delete", "delete", "parse"]:
        assert kw in kws, kw


def test_dotted_last_part_only_if_long_enough():
    kws = extract_keywords("see django.db.models.Q and os.path.join")
    assert "django.db.models.q" in kws and "q" not in kws
    assert "os.path.join" in kws and "join" in kws


def test_long_or_spaced_backtick_span_is_split():
    kws = extract_keywords("run `model.fit(X, y, sample_weight=w)` please")
    assert "sample_weight" in kws and "model.fit" in kws
    assert all(" " not in kw for kw in kws)


def test_stop_words_short_words_numbers_and_versions_are_dropped():
    kws = extract_keywords("The error is that this should return None in version 3.11, e.g. v2.0 fails. Use foo")
    for dropped in ["the", "error", "this", "should", "return", "none", "version", "3.11", "e.g", "v2.0", "use", "foo"]:
        assert dropped not in kws, dropped


def test_lowercase_no_duplicates_and_cap():
    kws = extract_keywords("Widget widget WIDGET `Widget`")
    assert kws == ["widget"]
    many = " ".join(f"name_{i}" for i in range(50))
    assert len(extract_keywords(many)) == MAX_KEYWORDS
    assert extract_keywords(many, max_keywords=5) == [f"name_{i}" for i in range(5)]


def test_no_keywords():
    assert extract_keywords("it is not ok") == []
    assert extract_keywords("") == []
