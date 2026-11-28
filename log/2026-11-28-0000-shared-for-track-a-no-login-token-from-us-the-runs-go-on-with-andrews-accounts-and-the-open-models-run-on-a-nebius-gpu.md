# For track A: no login token comes from us. The runs go on with Andrew's own accounts; tell us if the first leg is too much; the open models run on a Nebius GPU

- **Track:** shared: from the lead, for track A. Answers the request for login tokens in your entries of 19:35 and 22:21 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 00:00 UTC
- **Work package:** A12 (the runs), and the open models of the model gap
- **Branch, commits, pull request:** none

## Done

Three decisions of Andre's.

**1. We cannot send a login token.**

- A token from `claude setup-token` is valid for one year, and Claude Code's documentation describes no way to take a single token back.
- Sharing it is against Anthropic's consumer terms (section 2, effective Oct 8, 2025): "You may not share your Account login information, Anthropic API key, or Account credentials with anyone else." and "You also may not make your Account available to anyone else."
- Andre's judgment: an account used from another person's machine is easy to notice, and it could be banned.
- **So the runs go on with Andrew's own accounts for now.** Do not plan with a token from Andre. The same clause holds for a token from Wilson.

**2. If the first leg is too much for the PC and its accounts, say so here.** As we understand it, the PC has two accounts of Andrew's. The first leg is Haiku's repetition 1 (`docs/plan/runs.md` §7, step 2). If clearing it loads the PC or the accounts too heavily, write it in this log with what is falling behind. Some repos or tasks may then be handed over to us.

**3. The open models and their evals run on a Nebius GPU.** Andre sets it up and pays for it. This keeps the PC for the Claude runs: plan nothing of the open-model work on it.

## Checked

- The two sentences of the terms were read on anthropic.com/legal/consumer-terms on Nov 27. The token's lifetime, and that it "can only make model requests", are from code.claude.com/docs/en/authentication.
- Not checked: which plans Andrew's accounts are on. A Team or Enterprise plan is under other terms.

## Left

Nothing.

## Blocked on, or needed from others

- **Track A:** a line in this log as soon as the first leg is more than the PC or its accounts can carry.

## Next

The lead: the entry on the lock at 00:30 UTC.
