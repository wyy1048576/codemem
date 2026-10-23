"""Search words for the offline grep baselines, taken from an issue the way an agent would pick them.

Order matters, because the list is capped: text in backticks first (people put code names there),
then identifier-like tokens, then other meaningful words. Everything is lowercase, because the
search ignores case.
"""

from __future__ import annotations

import re

MAX_KEYWORDS = 20

# Words that match nearly every file or say nothing about where the code is.
STOP_WORDS = frozenset(
    """
    about above after again against also although always among another anything anyway around
    because been before being below between both cannot could does doing done down during each
    either else even ever every few first from further give given gives going good great have
    having here however into itself just keep know last least less like likely make makes many
    maybe might more most much must need needs never next none nothing once only other others otherwise
    over perhaps please probably quite rather really same seem seems seen several shall should
    since some something still such sure take than that their them then there these they thing
    things this those though through thus together under unless until upon used uses using very
    want wants well were what whatever when where whether which while will with within without
    work works would your yours
    error errors issue issues problem problems expected actual behavior behaviour version versions
    following example examples reproduce reproduces reproducing steps output result results
    instead currently correct correctly wrong fails failed failing raise raises raised thanks
    hello code test tests case cases call calls called line lines file files time
    self return returns none true false import imports class classes print from with pass def
    elif else lambda yield async await assert break continue global nonlocal object value values
    function functions method methods string strings list lists dict type types python
    """.split()
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*[A-Za-z0-9_]|[A-Za-z_]")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_ABBREVIATIONS = {"e.g", "i.e", "etc", "vs", "cf"}


def _looks_like_identifier(token: str, followed_by_paren: bool) -> bool:
    if "." in token:
        parts = token.split(".")
        if token.lower() in _ABBREVIATIONS or all(p.isdigit() for p in parts[1:]):
            return False  # "e.g", "v2.0"
        return True
    return "_" in token or any(c.isupper() for c in token[1:]) or followed_by_paren


def _candidates(text: str) -> tuple[list[str], list[str]]:
    """(identifier-like tokens, plain words) in order of appearance."""
    identifiers: list[str] = []
    words: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).strip(".")
        if not token:
            continue
        followed_by_paren = text[match.end() : match.end() + 1] == "("
        if _looks_like_identifier(token, followed_by_paren):
            identifiers.append(token)
            if "." in token:
                last = token.rsplit(".", 1)[-1]
                if len(last) >= 4:
                    identifiers.append(last)
        elif token.isalpha() and len(token) >= 4 and token.lower() not in STOP_WORDS:
            words.append(token)
    return identifiers, words


def extract_keywords(query: str, max_keywords: int = MAX_KEYWORDS) -> list[str]:
    """Search words for a query, best first, lowercase, no duplicates, at most max_keywords."""
    ordered: list[str] = []

    for span in _BACKTICK_RE.findall(query):
        span = span.strip().rstrip("()").strip(".,:;")
        if span and " " not in span and len(span) <= 60:
            ordered.append(span)
            if "." in span and len(span.rsplit(".", 1)[-1]) >= 4:
                ordered.append(span.rsplit(".", 1)[-1])
        else:
            identifiers, words = _candidates(span)
            ordered.extend(identifiers + words)

    identifiers, words = _candidates(query)
    ordered.extend(identifiers)
    ordered.extend(words)

    keywords: list[str] = []
    seen: set[str] = set()
    for word in ordered:
        word = word.lower()
        if word and word not in seen and word not in STOP_WORDS and len(word) >= 3:
            seen.add(word)
            keywords.append(word)
            if len(keywords) == max_keywords:
                break
    return keywords
