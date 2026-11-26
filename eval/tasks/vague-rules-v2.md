# Rules for writing the L1 and L2 versions of a task prompt (version 2)

Version 2 replaces the "Done when" rule of version 1. Version 1 allowed that line for anything
the hidden tests need; the lines became a copy of the tests in prose (13 of 18 tasks), which no
user writes, and which made the vague prompts easier than the original issues.

A task is a real GitHub issue of an open-source repo, with the real fix and the hidden tests that
grade a fix. A coding agent gets only the prompt text and the repo. We study whether a code-search
tool helps the agent find where to work. The original issue (level L0) usually names the function,
option, file or error, so the agent can find the place with a plain text search. You write two
vaguer versions of the same request. The change that is asked for, and the hidden tests, stay the same.

## L1: the same content, with the names removed
- Keep every fact of the issue that matters for the fix: what the user did, what happened, what
  should happen, the conditions under which it happens, versions or platforms if they matter.
- Remove: file paths; names of functions, methods, classes, attributes, variables, parameters,
  options, flags, config keys and error classes of the repo's code; stack traces; code snippets;
  exact log or error strings that exist in the repo's code. Describe them in plain words instead
  ("the option that sets the text for missing values", not its name).
- A reproduction given as code becomes a description in words of the same steps and data.
- The name of the project and general terms of its domain are fine (pandas, DataFrame, group-by,
  HDF5, Playwright, browser context, trace viewer). A term is general if a user who never read the
  source would use it. When in doubt, describe, do not name.
- No links, no issue numbers, no names of people.
- Length: what the content needs; usually 60 to 200 words. Plain prose, no markdown headings.

## L2: a short request in a user's voice
- 10 to 30 words, one or two sentences, the way a developer would type a request to a coding
  assistant: "X is broken when Y, please fix it", "Make X do Y".
- It names the symptom or the wanted behaviour, and nothing of the code. Same removal rules as L1.
- It may leave out details of the issue. It must not ask for a different or smaller change.

## The "Done when" line (narrow, and rare)
A real user does not know what the hidden tests check. So the line is allowed in one case only:
the tests call or read something NEW that the user would name when they ask for it: a new
function, parameter, option, flag, setting value or command that the real fix adds, or one exact
message that the user sees. Then add ONE last line that starts with "Done when:", of at most 25
words, in words a user could say. The L1 and L2 of a task get the same line.
- No exact internal values or limits, no list of cases, no error classes, no test data.
- Names of code that EXISTS before the fix are still not allowed. Describe an existing setting in
  words.

## Tasks that do not fit are removed
Before you write, compare the hidden tests (test.patch) with the request. Keep the task only if a
correct and general fix for the request passes all hidden tests, with no line or with the narrow
line above. Remove the task from the vague set if the tests need more: several cases that the
request does not imply, an exact internal value, a behaviour that the issue does not describe, or
a change to something unrelated. A removed task is not rewritten. Record the reason.

## Never
- Never say which file, module, class or function has to change.
- Never copy from real-fix.patch. You read it only to know which names are leaks and what is new.
- Never mention the tests, the benchmark, or that this is a rewrite.
