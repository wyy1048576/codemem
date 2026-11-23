# The embedding model: candidates listed, the choice is Andre's on Nov 24

- **Track:** C
- **Who:** Andre, with Claude Code
- **When:** 2026-11-23 03:10 UTC
- **Work package:** C8, and the experiment C-E7
- **Branch, commits, pull request:** `main`. The edit to `docs/plan/track-c-memory.md` (new §6.8) is in Andre's working tree, for him to commit

## Done

- **The candidates are listed in track C §6.8,** with what is known about each: today's jina 0.5B,
  SweRankEmbed-Small (137M, trained on issues), papr-embed-code-1-0.6b, Qwen3-Embedding-0.6B,
  EmbeddingGemma 2, and Qwen3-Embedding-8B through Nebius.
- **Andre decides on Nov 24.** Until he announces it here, everything runs on today's model.
- **Licences do not rule a model out.** Andre: all of our work is research output, not
  commercial. Models under a non-commercial licence can be used, with credit.

## Checked

- Read on Nov 22 in the CORE-Bench paper's own tables (arXiv 2606.11864, NDCG@10 on its
  issue-to-code level): jina 0.5B 20.8, Qwen3-8B 20.3, Qwen3-0.6B 17.0, a 0.6B fine-tuned on pull
  requests 26.5. On its classic code search level: Qwen3-8B 71.7, jina 0.5B 63.5.
- Read on the model cards: SweRankEmbed-Small and papr-embed-code-1-0.6b, as in §6.8.
- No model was run. None of these numbers is from our own tasks.

## Left

- The choice itself.
- A fair test of any model other than jina needs its own query prefix. Today codemem gives jina's
  prefixes to every local model.

## Blocked on, or needed from others

Nothing.

## Next

- **Andrew:** keep running on today's model. A switch would mean building every index again, so
  it will be announced here before the freeze of Nov 25, or not made for the full runs.
