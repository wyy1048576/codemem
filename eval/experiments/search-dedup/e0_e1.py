"""E0 and E1 of the 12:25 entry, from Andre's session records (no model call).

E0: the counts of the 12:25 table (Haiku, the tool arms), and what the repeats cost.
E1: replay each session's searches under `shorten` (dedup.py): text saved, with and without forgetting.
A card's size is its call's result_chars / cards; a one-line repeat is the card's head line, about 110
characters. Tokens = characters / 4. A result's text is read again on every later turn (cache read).

Usage: python e0_e1.py SESSIONS.jsonl
"""
import collections as C
import json
import sys

rows = [json.loads(x) for x in open(sys.argv[1], encoding="utf8") if x.strip()]
ONE_LINE = 110
ARMS = ("tool", "tool-v0", "tool-q")  # the 12:25 table's arms (tool+ is the 20 names in the first message)
haiku = [r for r in rows if r["model"] == "haiku" and r["arm"] in ARMS]
print("E0. Haiku sessions with the tool:", len(haiku), "arms", dict(C.Counter(r["arm"] for r in haiku)))
nsearch = C.Counter()
later_results = later_repeats = multi = gained = gained_flag = 0
for r in haiku:
    s = [c for c in r["calls"] if c["kind"] == "search_code"]
    nsearch[min(len(s), 4)] += 1
    if len(s) < 2:
        continue
    multi += 1
    seen = set(s[0]["cards"])
    gold = set(r["gold_functions"])
    name = lambda card: card.split(" ", 1)[1].split(".")[-1] if " " in card else card
    first_hit = any(name(x) in gold for x in s[0]["cards"])
    later_hit = False
    for c in s[1:]:
        later_results += len(c["cards"])
        later_repeats += sum(x in seen for x in c["cards"])
        later_hit |= any(name(x) in gold and x not in seen for x in c["cards"])
        seen |= set(c["cards"])
    gained += later_hit and not first_hit
    gained_flag += (not s[0]["gold_function_among_cards"]) and any(c["gold_function_among_cards"] for c in s[1:])
print(" searches per session (4 = four or more):", dict(sorted(nsearch.items())))
print(" sessions with 2+ searches:", multi, "| results of later searches:", later_results,
      "| already sent in the session:", later_repeats, f"({later_repeats / max(later_results, 1):.0%})")
print(" later search finds a gold function the first missed: by name", gained, "| by the records' flag", gained_flag, "of", multi)


def replay(r, forget=0):
    """(chars sent, chars saved, tokens saved incl. later cache reads) for one session under shorten."""
    calls, sent, n = r["calls"], {}, 0
    sent_chars = saved = saved_reads = 0
    tool_calls = [c for c in calls if c["kind"] in ("search_code", "get_chunk")]
    last_turn = r["turns"] or max(c["turn"] for c in calls)
    for c in tool_calls:
        n += 1
        if c["kind"] != "search_code" or not c["cards"]:
            continue
        per = c["result_chars"] / len(c["cards"])
        sent_chars += c["result_chars"]
        for x in c["cards"]:
            if x in sent and (not forget or n - sent[x] < forget):
                saved += per - ONE_LINE
                saved_reads += (per - ONE_LINE) * max(last_turn - c["turn"], 0)
            else:
                sent[x] = n
    return sent_chars, saved, saved_reads


print("\nE1. shorten, replayed (Haiku tool sessions):")
for forget in (0, 10, 3):
    tot = [replay(r, forget) for r in haiku]
    sc, sv, rd = (sum(x[i] for x in tot) for i in range(3))
    touched = sum(1 for x in tot if x[1] > 0)
    print(f" forget after {forget or 'never'}: search text {sc:,.0f} chars, saved {sv:,.0f} ({sv / sc:.0%}); "
          f"sessions that save: {touched}; new-text tokens saved {sv / 4:,.0f}, later cache-read tokens saved {rd / 4:,.0f}")
sonnet = [r for r in rows if r["model"] == "sonnet" and r["arm"] in ARMS]
print(" Sonnet tool sessions:", len(sonnet), "with 2+ searches:",
      sum(1 for r in sonnet if sum(c["kind"] == "search_code" for c in r["calls"]) > 1))
