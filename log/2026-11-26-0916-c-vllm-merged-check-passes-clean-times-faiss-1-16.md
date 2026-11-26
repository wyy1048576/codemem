# Track C: the repo's check script passes on vLLM; the search times taken again; FAISS 1.16.0 is faster on Apple processors

- **Track:** C. Point 4 is for track B, point 3 touches track A's PC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 09:16 UTC
- **Work package:** C2, C3
- **Branch, commits, pull request:** `andre/track-c-results` (`b3046f2`, no pull request). No code changed since the entry of 07:43

## Done

**1. `scripts/check_search_indexes.py` on the real vLLM index: PASS.** The default rule and the
compact index at 4 bits returned the same top 10, the same top 50 and the same 10 merged results
in the same order as the exact index for all 381 questions. So did 2 bits with 500 candidates and
1 bit with 1,000. With 1 bit and 500 the merged 10 differed for 4 questions; none of the 4
gained or lost a gold file.

**2. The search times, taken again with no other job of ours running.** These replace the
milliseconds of the entry of 07:43 (the indexes took turns question by question; medians):

| One search | exact | compact, the default |
|---|---|---|
| vLLM, 109,562 code vectors | 11.4 ms | 10.9 ms |
| vLLM, 35,167 usage vectors | 3.4 ms | 5.7 ms |
| pandas, 43,187 code vectors | 4.1 ms | 6.2 ms |
| pandas, 6,583 usage vectors | 0.8 ms | 4.0 ms |

The reading stays: the compact index is slower on a small index, level at about 110,000 vectors,
faster beyond, and its gain is memory (278 MB against 106 MB on vLLM).

**3. FAISS 1.16.0 is faster on Apple processors, with the same results.** FAISS 1.15.1, the
version the lock file pins, has no vectorized RaBitQ code for ARM: its ARM file calls the plain
loops. Intel and AMD have vectorized ones. FAISS 1.16.0 (November 9) adds the ARM ones.

| One search, vLLM | FAISS 1.15.1 | FAISS 1.16.0 |
|---|---|---|
| exact, code vectors | 11.4 ms | 8.1 ms |
| compact, the default, code vectors | 10.9 ms | 7.0 ms |
| compact, the first scan keeping 4,000 codes | 13.5 ms | 7.5 ms |

- Under 1.16.0, in a scratch environment on the Mac: every FAISS call the store makes ran (2,608
  combinations), the default against the oracle on vLLM gave 762 of 762 again, and the combined
  branch's suite passed (622; 619 and 3 skipped on the compact index).
- Not done under 1.16.0: the run under the memory checker, and Linux.
- **Nothing is changed.** The lock file still pins 1.15.1. Whether to move it is Andre's
  decision; if yes, as a pull request of its own after #36.
- A quick read of FAISS's RaBitQ source (1.15.1) found nothing wrong: it is adapted from the
  paper authors' reference library, its estimate is unbiased in our measurement, and the 4-bit
  code is the sign bit and 3 bits of size, as the paper describes.

**4. For track B: how close one search gets.** The same vLLM run as the entry of 07:58 (whole
issue texts, exact index, one commit of vLLM), for the 342 tasks with a gold function in the
index:

| After one search | With 10 results | With 20 results |
|---|---|---|
| a gold function is a result | 60% | 68% |
| else a gold function is one call away from a result (caller, callee, or its class) | 10% | 11% |
| else it is in the same file as a result | 5% | 5% |
| else in the same folder | 9% | 6% |
| none of these | 15% | 11% |

It fits track A's finding that an agent makes one call and then greps: after 10 results the
agent holds the function, a neighbour of it, or its file in 75% of the tasks.

## Checked

- Point 1 is the script's own verdict line and JSON; the raw results per question are kept.
- Point 2 and 3: three passes over every question of the repo, both versions one after the
  other. The load average of the machine was 3 to 4 from other applications.
- Point 4 uses the index's call edges (`edges`) and the chunk's parent; labels are matched by
  path and qualified name.

## Left

- #34, #35, #36 (Andre merges). The fixes the audits asked for. The decision on FAISS 1.16.0.

## Blocked on, or needed from others

- **Andrew:** the check on the PC is still wanted before #36. On the PC, FAISS 1.15.1 already
  has vectorized RaBitQ code, so the time columns of the check script's table are worth sending
  back as well: they would show the compact index against the exact one on x86.

## Next

- Andre: the merges, and the decisions of point 3 and of the entry of 07:58.
