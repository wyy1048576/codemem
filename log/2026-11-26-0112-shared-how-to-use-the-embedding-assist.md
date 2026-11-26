# For all tracks: how to use the embedding assist, an optional second source of embeddings for a first build

- **Track:** C. For tracks A and B, and for anyone who builds an index on a slow machine
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 01:12 UTC
- **Work package:** C8 (docs/plan/track-c-memory.md §6.5, §6.6)
- **Branch, commits, pull request:** `andre/embedding-assist`, pushed, and in `andre/track-c-all`. Not on `main` yet: it merges fourth, after `andre/worktree-start`

## Done

Nothing new was built. This entry says how to use what the branch has. The full text is the
branch's README, "A second source for a build's embeddings".

**1. What it is.** A first build is almost all model time. With an assist set, the local model
and a second endpoint embed a build's texts at the same time. The endpoint is reached over an API:
any OpenAI-style `/v1/embeddings` endpoint that serves the same model. That is either a
`codemem serve-embeddings` server on a machine with a GPU, or a hosted provider. It is off unless
`[embedding.assist]` is set, and without it nothing changes.

**2. Route 1: a codemem server on a machine with a GPU.**

On the machine with the GPU (it prints the settings a client needs):

```bash
codemem serve-embeddings --host <an address the other machine can reach>     # the port is 8791
```

On the machine that builds, in `~/.codemem/config.toml` or in the repo's `.codemem.toml`:

```toml
[embedding.assist]
base_url = "http://<the GPU machine>:8791/v1"
model = "jinaai/jina-code-embeddings-0.5b"     # the model the server prints at its start
api_key_env = "CODEMEM_SERVE_KEY"              # only if the server was started with a key
```

**3. Route 2: a hosted API that serves the model.** The same section with the provider's address,
its name for the model, and the environment variable that holds its key. The README has an
example for Jina's API and the three things to find out about a provider first (who adds the
model's prompt, which request field selects it, whether vectors are normalized). That example has
not been run.

**4. Then, on the machine that builds:**

```bash
codemem status --check-assist     # embeds seven fixed texts both ways; exit status 0: the endpoint can be used
codemem index <repo>              # or: codemem init
```

**5. What to know before you set it.**

| | |
|---|---|
| Code leaves the machine | with it set, a build's code texts go to the endpoint, and `codemem status` says so. Fine for the eval's public repos. Not for private code without its owner's word |
| The key | only in the environment variable that `api_key_env` names. Never in a file or a log |
| Which work is shared | the large embedding calls of `codemem index` and `codemem init`. Edits, queries, a search's catch-up and a build that the MCP server makes in the background stay with the local model. So build with `codemem index` first |
| The index it gives | the one the local model alone would build: every vector is stored under the local model's key. No index key changes |
| The check | before the endpoint gets any text, each of seven probe vectors must agree with the local model's to a cosine of 0.99995. Below that the endpoint gets nothing, the build goes on alone, and `codemem status` says why in one line |
| A long text | a text that the local model would cut (over 1,024 tokens) is never sent |
| When the endpoint fails or is slow | its texts go back to the local model within the same call. A build never waits for it |
| Not together | `[embedding]` with `provider = "openai"` is for a machine that runs no model of its own. `[embedding.assist]` is for one that runs the model and wants help. Set one of them |

**6. For track A.** The PC has the GPU and needs no assist. Leave it unset for runs whose numbers
are reported: an endpoint's vectors agree with the local model's to a cosine of 0.99995, which is
not always bit for bit.

## Checked

- The instructions above are the branch's README and its `AssistConfig`, read again for this
  entry. Nothing was run for it.
- The feature itself: 48 tests with stand-in models. With stand-in models of set speeds a build
  ran 1.87 times as fast with an endpoint as fast as the local model, and 3.4 times with one four
  times as fast.
- **Not checked: a real model, any hosted provider, a server on a second machine.** A provider
  that runs the model in another precision may not reach the bar: bfloat16 against float16
  measured 0.99978 here.

## Left

- A first real trial. It needs a provider's key, or a second machine that runs the server.

## Blocked on, or needed from others

- Nothing.

## Next

- Track C's session: the trial, when Andre has a key or a second machine for it.
