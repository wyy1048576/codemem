# Rules for writing the L1 and L2 versions of a task prompt

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

## The "Done when" line (both levels, only when needed)
Read the hidden tests (test.patch). If a correct fix could still fail them because they need
something that neither the prompt nor common sense gives, add ONE last line that starts with
"Done when:" and states exactly that, and nothing more. Typical cases:
- the tests call a NEW function, method, parameter, option, flag, file or CLI command by name
  (new = added by the real fix, not in the repo before): give the name and its signature or use;
- the tests assert an exact value, limit, message text, or output format that the issue does not
  determine (for example a chunk size, an exact error message);
- the tests cover an extra case that the issue does not mention: state the case in words.
Names that the fix ADDS are allowed in this line. Names of code that EXISTS before the fix are
still not allowed, with one exception: if the tests call an existing public API whose name a user
must know to use the feature at all, you may describe it in words instead.
If the tests need nothing extra, write no "Done when" line. The L1 and L2 of a task get the same
"Done when" line.

## Never
- Never say which file, module, class or function has to change.
- Never copy from real-fix.patch. You read it only to know which names are leaks and what is new.
- Never mention the tests, the benchmark, or that this is a rewrite.
