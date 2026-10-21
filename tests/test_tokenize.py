from codemem.tokenize import fts_match_query, split_identifier, tokenize


def test_snake_case_keeps_full_identifier():
    assert tokenize("revoke_session") == ["revoke", "session", "revoke_session"]


def test_camel_case_keeps_full_identifier():
    assert tokenize("getUserById") == ["get", "user", "by", "id", "getuserbyid"]


def test_acronyms_and_pascal_case():
    assert split_identifier("HTTPServerError") == ["http", "server", "error"]
    assert split_identifier("parseHTML5Doc") == ["parse", "html", "5", "doc"]


def test_dots_and_punctuation_split():
    assert tokenize("db.sessions.delete(x)") == ["db", "sessions", "delete", "x"]


def test_single_word_not_duplicated():
    assert tokenize("Users") == ["users"]


def test_leading_underscores():
    assert tokenize("__init__") == ["init"]
    assert tokenize("_private_helper") == ["private", "helper", "private_helper"]


def test_optional_stemming_and_stopwords():
    assert tokenize("the users logged in", stopwords=True) == ["users", "logged"]
    assert tokenize("users sessions queries", stem=True) == ["user", "session", "query"]
    # Off by default.
    assert tokenize("users") == ["users"]


def test_fts_query_is_safe_for_syntax_characters():
    q = fts_match_query('foo AND "bar" NEAR(baz) * ^col: -x')
    assert q == '"foo" OR "and" OR "bar" OR "near" OR "baz" OR "col" OR "x"'
    assert fts_match_query("!!! ???") is None


def test_fts_query_dedupes():
    assert fts_match_query("get get_user") == '"get" OR "user" OR "get_user"'
