"""No search result paid for twice in one session (config `search_dedup`; off by default).

The MCP server runs one process per agent session, so what this session was sent is kept here, in
memory: for each chunk key, the chunk's `content_hash` when it was sent, a hash of the card text sent
(without its number on the page), how it was sent (a card, or in full by get_chunk), and at which call.

A later `search_code` page walks the ranking in order. A result is shown SHORT (its head line as on
a card: number, current `path:line`, name and id; then one line "(shown earlier ..., unchanged)") only
when all of these hold:
  - the session was sent it, at most `search_dedup_forget_calls` tool calls ago;
  - its code is unchanged since (same `content_hash` in the index now);
  - the card would read the same (same card hash), or it was sent in full by get_chunk;
  - the index is current for this search (`Freshness.complete`: no saved file still being applied,
    no chunk still being embedded, every save confirmed, not an unchecked copy);
  - the query is not one this session already sent (same words, path_prefix, kinds and tests): the
    same query again gives every result as a card, so the agent can always have the cards back.
Otherwise the result is a full card. A card for a result whose code changed since it was sent says
"changed since shown earlier"; one whose code is the same but whose card shows other lines says
"shown earlier, other lines this time". Repeats keep their place in the order. Every mark is a line of
its own under the head line, so the head line reads as on any card (the eval parses head lines:
eval/src/cmeval/e2e_replay.py, _HEAD).

A session is one MCP client: a call from a client other than the last one (by the name and version of
its `initialize`) starts an empty memory. The eval's gate (eval/src/cmeval/codemem_gate.py) warms the server with its own handshake and
search, then relays Claude Code's handshake to the same process; the gate's search is not the agent's.

`shorten` shows the same k results as `off`, repeats as one line. `refill` goes on down the ranking
until the page has k full cards (or the ranking ends), so the slots a repeat took go to results the
session has not seen. get_chunk is never shortened; it only records what it sent.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .render import card_label, format_card
from .search import ResultCard, SearchResponse
from .store import Store

MODES = ("off", "shorten", "refill")
REFILL_DEPTH = 50  # refill asks the ranking for at most this many results beyond k


@dataclass
class Sent:
    content_hash: str
    card_hash: str  # "" when sent in full by get_chunk
    how: str  # "card" | "full"
    call: int


def _card_hash(lines: list[str]) -> str:
    text = "\n".join(lines)
    text = re.sub(r"^\d+\. ", "", text)  # the number on the page is not part of what was seen
    return hashlib.sha1(text.encode("utf8")).hexdigest()


def _query_key(query: str, path_prefix: str | None, kinds: list[str] | None, tests: str) -> tuple:
    return (" ".join(query.lower().split()), path_prefix or "", tuple(sorted(kinds or [])), tests)


class SessionMemory:
    """What one MCP session (one server process) was sent."""

    def __init__(self, mode: str = "off", forget_calls: int = 10):
        if mode not in MODES:
            raise ValueError(f"search_dedup must be one of {MODES}, got {mode!r}")
        self.mode, self.forget_calls = mode, forget_calls
        self.sent: dict[str, Sent] = {}
        self.queries: set[tuple] = set()
        self.calls = 0
        self.stats = {"searches": 0, "one_line": 0, "cards": 0, "changed": 0, "other_lines": 0, "refilled": 0}
        self._client: object = None

    def for_client(self, client: object) -> None:
        """`client`: who is calling (server._client_of: the name and version of its `initialize`). A new
        client forgets everything an earlier one was sent."""
        if client != self._client:
            self._client = client
            self.sent, self.queries, self.calls = {}, set(), 0

    @property
    def on(self) -> bool:
        return self.mode != "off"

    def _forget(self) -> None:
        if self.forget_calls:
            old = [key for key, s in self.sent.items() if self.calls - s.call >= self.forget_calls]
            for key in old:
                del self.sent[key]

    def depth(self, k: int, query: str, path_prefix: str | None, kinds: list[str] | None, tests: str) -> int:
        """How many results to ask the ranking for."""
        if self.mode != "refill" or _query_key(query, path_prefix, kinds, tests) in self.queries:
            return k
        return k + min(len(self.sent), REFILL_DEPTH)

    def page(self, resp: SearchResponse, k: int, store: Store, *, current: bool, path_prefix: str | None = None,
             kinds: list[str] | None = None, tests: str = "include") -> str:
        """The text of one search_code page. `current`: the index was current for this search."""
        self.calls += 1
        self._forget()
        self.stats["searches"] += 1
        qkey = _query_key(resp.query, path_prefix, kinds, tests)
        again = qkey in self.queries
        self.queries.add(qkey)
        if not resp.results:
            return f"No results for {resp.query!r}."
        hashes = {cid: c.content_hash for cid, c in store.get_chunks([r.chunk_id for r in resp.results]).items()}
        out: list[str] = []
        full = repeats = 0
        for i, r in enumerate(resp.results, start=1):
            if full >= k:
                break
            card = format_card(r, i)
            chash, now = _card_hash(card), hashes.get(r.chunk_id)
            prev = self.sent.get(r.key)
            unchanged = prev is not None and now is not None and prev.content_hash == now
            if unchanged and current and not again and (prev.how == "full" or prev.card_hash == chash):
                out.append(self._one_line(r, i, prev))  # not a new send: its call stays as it was
                repeats += 1
                self.stats["one_line"] += 1
                continue
            if prev is not None and not unchanged:
                card.insert(1, "   (changed since shown earlier)")
                self.stats["changed"] += 1
            elif prev is not None and prev.how == "card" and prev.card_hash != chash:
                card.insert(1, "   (shown earlier, other lines this time)")
                self.stats["other_lines"] += 1
            out.extend(card)
            full += 1
            self.stats["cards"] += 1
            if i > k:
                self.stats["refilled"] += 1
            if now is not None:
                keep_full = unchanged and prev.how == "full"
                self.sent[r.key] = Sent(now, "" if keep_full else chash, "full" if keep_full else "card", self.calls)
        if repeats:
            out.append("")
            if self.mode == "refill" and full < k:
                out.append(f"Only {full} of these results are new to this session.")
            out.append(f"{repeats} result{'s' if repeats > 1 else ''} shown short: sent earlier in this session and "
                       "unchanged since. get_chunk(id) returns the current code; this same query again shows every "
                       "result as a card.")
        return "\n".join(out)

    def _one_line(self, r: ResultCard, i: int, prev: Sent) -> str:
        how = "in full by get_chunk" if prev.how == "full" else "as a card"
        return f"{i}. {r.location}  {card_label(r)}  [id {r.chunk_id}]" + chr(10) + f"   (shown earlier {how}, unchanged)"

    def got_chunk(self, key: str, content_hash: str, whole: bool) -> None:
        """get_chunk sent this chunk; `whole`: its full code (not a long class's outline)."""
        self.calls += 1
        self._forget()
        if whole:
            self.sent[key] = Sent(content_hash, "", "full", self.calls)
