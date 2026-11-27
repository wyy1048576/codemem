# For track B: one more case for item 2. Results the session has only seen by name, such as the list in the first message

- **Track:** shared: from Andre, for track B. It adds to the work package of 12:25 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 13:25 UTC
- **Work package:** B8
- **Branch, commits, pull request:** none

## Done

**Andre's question:** does the rule for repeated results take into account what the agent was given up front, the 20 names in the first message?

**Where it matters.** Not in track A's runs: there `tool` and `upfront` are separate setups, so a list and a later search never meet. It matters for the product, where codemem may give the list at the start and keep the tool on. So this is a case for the design and the write-up. Nothing new has to be built for the runs.

**The rule we would start from (yours to test or replace):**

- **A name is not the code.** A result the session has only seen by name (in the list of the first message, or in a "more results by name" block) has not been shown. A later search that returns it shows the full card, because the signature and the code lines are new. Never shorten it.
- **Three levels, then:** named only; shown as a card; read in full through `get_chunk`. Only the last two can make a later result a repeat.
- **The server knows the list only if the server made it.** In our test the list was made outside the server. If the product makes it through the running server, the server can mark such a card "in the list above". Say in the write-up which way you would have it.

**What we saw with both together** (34 sessions today, the list in the first message and the tool still offered): Haiku searched at turn 1 in 12 of 17 sessions although it had the list, with a query of its own; Sonnet never called the tool. So the waste in that case is the extra search, not a repeated card. Your write-up should say what the tool ought to do, or say, when a list was already given.

## Checked

The 34 sessions: counted from the raw records on the Mac.

## Left

Nothing on our side.

## Blocked on, or needed from others

**Track B:** this case in the design and the write-up of item 2.

## Next

Andre's session: the review of what track B posts, from 22:00 UTC.
