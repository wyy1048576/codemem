"""codemem retrieval with Sonnet query augmentation. Same index, same RRF formula as cm3-full.

Ranked lists: the whole issue (BM25, code, usage), intent + symptom (code, usage), and anchors
(BM25). `guess=True` adds guessed locations as one BM25 list at weight 0.25. Chunks at a location
the issue explicitly states are pinned first. `mode="revise"` shows Sonnet the top 10 cards of the
one-shot arm (no guesses) and retrieves with its revised extraction. `mode="diagnose"` uses the v2
one-shot prompt (diagnosis + suspects) and its own intent, symptom and anchors for the same six lists;
`suspects=True` adds a dense list on "diagnosis + suspects" (code, usage) and BM25 on the suspects, each at
weight 0.5, unless the diagnosis is "none" or there are no suspects.
`mode="loop"` uses codemem the way an agent uses grep: round 1 is the one-shot top 50; Sonnet judges whether
the code to change is there, picks results, and writes the next query (intent, anchors, folders to look in).
Later rounds show only results not seen before. It stops when Sonnet says found, or after `max_rounds`.
The final list is the picks, then RRF over every round's ranking.
"""
from __future__ import annotations

import hashlib
import os
import re

from cmeval.adapters.codemem import _SHARED, CodememRetriever
from cmeval.retriever import Hit
from cmeval.tasks import load_tasks
from codemem.embedder import make_embedder
from codemem.render import format_results
from codemem.search import SearchResponse, _pick_top, make_card, rrf, search

import llm

GUESS_WEIGHT = 0.25
SUSPECT_WEIGHT = 0.5
LOOP_SHOWN = 50
LOOP_POOL = 100
LOOP_CARD_CHARS = 500
FULL_CODE_CHARS = 4000  # full_code=True: each result's whole source from the index, cut at this length
MAX_PINS = 10
PINS_PER_LOCATION = 3
CARD_CHARS = 700
EXTENSION = re.compile(r"\.[A-Za-z0-9+]{1,6}$")
_vectors: dict[tuple, object] = {}


class _MemoEmbedder:
    """The same query text gets the same vector once, across arms."""

    def __init__(self, spec, config):
        self.key = (spec.model, spec.embedder, spec.version)
        self.inner = make_embedder(spec, config)

    def embed_queries(self, texts):
        out = []
        for text in texts:
            key = (*self.key, text)
            if key not in _vectors:
                _vectors[key] = self.inner.embed_queries([text])[0]
            out.append(_vectors[key])
        return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


class AugRetriever(CodememRetriever):
    def __init__(self, name="aug", signals=None, config=None, mode="oneshot", guess=False, suspects=False, max_rounds=5, full_code=False):
        if mode not in ("oneshot", "revise", "diagnose", "loop"):
            raise ValueError(f"mode {mode!r}")
        if suspects and mode != "diagnose":
            raise ValueError("suspects needs mode='diagnose'")
        super().__init__(name, signals, config)
        if full_code and mode != "loop":
            raise ValueError("full_code needs mode='loop'")
        self.mode, self.guess, self.suspects, self.max_rounds = mode, bool(guess), bool(suspects), int(max_rounds)
        self.full_code = bool(full_code)
        self.tasks = {_sha(t.query): t for t in load_tasks(os.environ["AUG_TASKS"])}

    def describe(self):
        return {**super().describe(), "augmentation": {
            "mode": self.mode, "guess": self.guess, "suspects": self.suspects,
            "prompt_sha": {"diagnose": llm.PROMPT_SHA_V2, "loop": llm.PROMPT_SHA_LOOP}.get(self.mode, llm.PROMPT_SHA),
            "model": llm.MODEL, "effort": llm.EFFORT, "max_rounds": self.max_rounds, "loop_shown": LOOP_SHOWN,
            "loop_pool": LOOP_POOL, "loop_card_chars": LOOP_CARD_CHARS, "full_code": self.full_code,
            "full_code_chars": FULL_CODE_CHARS,
            "guess_weight": GUESS_WEIGHT, "suspect_weight": SUSPECT_WEIGHT, "max_pins": MAX_PINS, "pins_per_location": PINS_PER_LOCATION}}

    def _ranked(self, store, text: str, signal: str, n: int | None = None, path_prefix: str | None = None) -> list[int]:
        response = search(store, text, self.config, k=n or self.config.candidates, signals=[signal],
                          path_prefix=path_prefix, embedder_factory=_MemoEmbedder)
        return [card.chunk_id for card in response.results]

    def _location_ids(self, store, location: str, issue: str, scores: dict[int, float]) -> list[int]:
        text = location.strip().strip("`'\"").replace("\\", "/").removeprefix("./")
        text = re.sub(r":\d+(?::\d+)?$", "", text)
        if "/" in text or (EXTENSION.search(text) and "::" not in text):
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            paths = [r[0] for r in store.conn.execute(
                "SELECT DISTINCT path FROM chunks WHERE path = ? OR path LIKE ? ESCAPE '\\'", (text, f"%/{escaped}"))]
            if not paths or len(paths) > 3:
                return []
            ids: list[int] = []
            for path in paths:
                found = [c.chunk_id for c in search(store, issue, self.config, k=PINS_PER_LOCATION, signals=["bm25"],
                                                    path_prefix=path).results if c.path == path]
                if not found:
                    found = [r[0] for r in store.conn.execute(
                        "SELECT chunk_id FROM chunks WHERE path = ? ORDER BY start_line LIMIT ?", (path, PINS_PER_LOCATION))]
                ids += found
        else:
            symbol = re.sub(r"\(.*$", "", text).strip()
            parts = [p for p in re.split(r"::|->|\.", symbol) if p]
            if not parts:
                return []
            rows = store.conn.execute("SELECT chunk_id, qualname FROM chunks WHERE name = ?", (parts[-1],)).fetchall()
            if len(parts) > 1:
                suffix = f"{parts[-2]}.{parts[-1]}"
                rows = [r for r in rows if r[1].endswith(suffix)] or rows
            in_pool = [r[0] for r in rows if r[0] in scores]
            ids = in_pool or ([r[0] for r in rows] if len(rows) <= PINS_PER_LOCATION else [])
        return sorted(dict.fromkeys(ids), key=lambda c: (-scores.get(c, 0.0), c))[:PINS_PER_LOCATION]

    def _retrieve(self, store, issue: str, extraction: dict, guess: bool, k: int, suspects: bool = False):
        ranked = {f"whole_{s}": self._ranked(store, issue, s) for s in ("bm25", "code", "usage")}
        dense = f"{extraction['intent']}\n{extraction['symptom']}"
        for signal in ("code", "usage"):
            ranked[f"llm_{signal}"] = self._ranked(store, dense, signal)
        if extraction["anchors"]:
            ranked["anchors_bm25"] = self._ranked(store, " ".join(extraction["anchors"]), "bm25")
        weights = {name: 1.0 for name in ranked}
        if guess and extraction["guessed_location"]:
            ranked["guess_bm25"] = self._ranked(store, " ".join(extraction["guessed_location"]), "bm25")
            weights["guess_bm25"] = GUESS_WEIGHT
        diagnosis = extraction.get("diagnosis", "").strip()
        if suspects and extraction.get("suspects") and diagnosis.lower().rstrip(".") != "none":
            names = " ".join(extraction["suspects"])
            for signal in ("code", "usage"):
                ranked[f"diag_{signal}"] = self._ranked(store, f"{diagnosis}\n{names}", signal)
                weights[f"diag_{signal}"] = SUSPECT_WEIGHT
            ranked["suspects_bm25"] = self._ranked(store, names, "bm25")
            weights["suspects_bm25"] = SUSPECT_WEIGHT
        fused = rrf(ranked, k=self.config.rrf_k, weights=weights)
        scores = dict(fused)
        pins: list[int] = []
        for location in extraction["stated_location"]:
            pins += self._location_ids(store, location, issue, scores)
        pins = list(dict.fromkeys(pins))[:MAX_PINS]
        rank_of = {name: {c: r for r, c in enumerate(ids, start=1)} for name, ids in ranked.items()}

        def ranks(chunk_id):
            return {name: rank_of[name][chunk_id] for name in ranked if chunk_id in rank_of[name]}

        chunks = store.get_chunks(pins)
        picked = [(chunks[c], 1.0 + scores.get(c, 0.0)) for c in pins if c in chunks]
        chosen = {chunk.chunk_id for chunk, _ in picked}
        picked += _pick_top([item for item in fused if item[0] not in chosen], max(k - len(picked), 0), store.get_chunks)
        cards = [make_card(chunk, score, self.config, ranks(chunk.chunk_id)) for chunk, score in picked[:k]]
        return cards, {"pins": len(chosen), "lists": {name: len(ids) for name, ids in ranked.items()}}

    def _prefix(self, store, location: str) -> str | None:
        """A file or folder the index has, as a path prefix; None when it has neither."""
        text = location.strip().strip("`'\"").replace("\\", "/").removeprefix("./").strip("/")
        if not text:
            return None
        if store.conn.execute("SELECT 1 FROM chunks WHERE path = ? LIMIT 1", (text,)).fetchone():
            return text
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if store.conn.execute("SELECT 1 FROM chunks WHERE path LIKE ? ESCAPE '\\' LIMIT 1", (escaped + "/%",)).fetchone():
            return text + "/"
        return None

    def _round_fused(self, store, query: dict) -> list[tuple[int, float]]:
        """Rounds 2+: the new query's dense lists and anchor BM25, plus the same kind of lists limited to each look_in path."""
        dense = f"{query['intent']}\n{query['symptom']}"
        words = " ".join(query["anchors"]) or dense
        ranked = {f"llm_{s}": self._ranked(store, dense, s, LOOP_POOL) for s in ("code", "usage")}
        if query["anchors"]:
            ranked["anchors_bm25"] = self._ranked(store, words, "bm25", LOOP_POOL)
        for i, prefix in enumerate(query["look_in"]):
            ranked[f"in{i}_bm25"] = self._ranked(store, words, "bm25", path_prefix=prefix)
            ranked[f"in{i}_code"] = self._ranked(store, dense, "code", path_prefix=prefix)
        return rrf(ranked, k=self.config.rrf_k)

    def _show(self, cards, store=None) -> str:
        """Numbered results: 500-character previews, or with full_code the card's header line plus the chunk's
        whole source from the index (cut at FULL_CODE_CHARS)."""
        full = getattr(self, "full_code", False) and store is not None
        chunks = store.get_chunks([c.chunk_id for c in cards]) if full else {}
        out = []
        for i, card in enumerate(cards, start=1):
            text = format_results(SearchResponse("", ["llm"], [card]))
            text = f"{i}." + text[2:] if text.startswith("1.") else text
            chunk = chunks.get(card.chunk_id)
            if chunk is None:
                out.append(text[:LOOP_CARD_CHARS])
                continue
            code = chunk.code
            if len(code) > FULL_CODE_CHARS:
                rest = code[FULL_CODE_CHARS:].count("\n") + 1
                code = code[:FULL_CODE_CHARS] + f"\n[... {rest} more lines not shown]"
            out.append(text.split("\n", 1)[0] + "\n" + code)
        return "\n\n".join(out)

    def _loop(self, store, task, k: int):
        first = llm.clean(llm.extract("oneshot", llm.oneshot_input(task.repo, task.query))["output"], task.query)
        cards, _ = self._retrieve(store, task.query, first, False, LOOP_SHOWN)  # the one-shot arm's top 50
        query = {key: first[key] for key in ("intent", "symptom", "anchors")} | {"look_in": []}
        history = [{"round": 1, "query": query}]
        lists: dict[str, list[int]] = {"r1": [c.chunk_id for c in cards]}
        seen: set[int] = set()
        seen_text, picks, cost, found = "", [], 0.0, False
        for round_no in range(1, self.max_rounds + 1):
            if round_no > 1:
                fused = self._round_fused(store, query)
                lists[f"r{round_no}"] = [c for c, _ in fused[:LOOP_POOL]]
                fresh = _pick_top([item for item in fused if item[0] not in seen], LOOP_SHOWN, store.get_chunks)
                cards = [make_card(chunk, score, self.config) for chunk, score in fresh]
            if not cards:
                break
            shown = self._show(cards, store)
            seen.update(c.chunk_id for c in cards)
            seen_text += "\n" + shown
            record = llm.extract("loop_full" if self.full_code else "loop",
                                 llm.loop_input(task.repo, task.query, history, round_no, shown))
            cost += record.get("cost_usd") or 0.0
            out = llm.clean_loop(record["output"], task.query, seen_text, len(cards))
            picked = [cards[p - 1] for p in out["picks"]]
            picks += [c.chunk_id for c in picked if c.chunk_id not in picks]
            history[-1].update(analysis=out["analysis"], picked=[f"{c.path}:{c.qualname}" for c in picked],
                               found=out["found"], shown=len(cards), dropped_anchors=out["dropped_anchors"],
                               dropped_picks=out["dropped_picks"], look_in_asked=out["look_in"])
            found = out["found"]
            if found or round_no == self.max_rounds:
                break
            look_in = [p for p in (self._prefix(store, x) for x in out["look_in"]) if p]
            query = {"intent": out["intent"], "symptom": out["symptom"], "anchors": out["anchors"], "look_in": look_in}
            history.append({"round": round_no + 1, "query": query})
        fused = rrf(lists, k=self.config.rrf_k)
        scores = dict(fused)
        chunks = store.get_chunks(picks)
        final = [(chunks[c], 1.0 + scores.get(c, 0.0)) for c in picks if c in chunks]
        chosen = set(picks)
        final += _pick_top([item for item in fused if item[0] not in chosen], max(k - len(final), 0), store.get_chunks)
        cards = [make_card(chunk, score, self.config) for chunk, score in final[:k]]
        trace = {"rounds": len(history), "found": found, "picks": len(picks), "cost_usd": round(cost, 4), "history": history}
        return cards, trace

    def search(self, query: str, k: int) -> list[Hit]:
        task = self.tasks.get(_sha(query))
        if task is None:  # the runner's warm-up query
            return super().search(query, k)
        store = _SHARED[self._index_dir]["service"].store
        if self.mode == "loop":
            return self._hits(*self._loop(store, task, k))
        kind = "oneshot_v2" if self.mode == "diagnose" else "oneshot"
        first_record = llm.extract(kind, llm.oneshot_input(task.repo, task.query))
        extraction = llm.clean(first_record["output"], task.query)
        if self.mode == "revise":
            first_cards, _ = self._retrieve(store, task.query, extraction, False, 10)
            shown = "\n\n".join(format_results(SearchResponse(task.query, ["llm"], [card]))[:CARD_CHARS] for card in first_cards)
            record = llm.extract("revise", llm.revise_input(task.repo, task.query, extraction, shown))
            extraction = llm.clean(record["output"], task.query, shown)
        cards, trace = self._retrieve(store, task.query, extraction, self.guess, k, self.suspects)
        trace["extraction"] = extraction
        return self._hits(cards, trace)

    def _hits(self, cards, trace) -> list[Hit]:
        hits = []
        for rank, card in enumerate(cards, start=1):
            text = format_results(SearchResponse("", ["llm"], [card]))
            text = f"{rank}." + text[2:] if text.startswith("1.") else text
            hits.append(Hit(path=card.path, start_line=card.start_line, end_line=card.end_line, symbol=card.qualname,
                            score=card.score, text=text, extra={"ranks": card.ranks or {}, "kind": card.kind,
                                                               "chunk_id": card.chunk_id, "language": card.language}))
        if hits:
            hits[0].extra["augmentation"] = trace
        return hits
