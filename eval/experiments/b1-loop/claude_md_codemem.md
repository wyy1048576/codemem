# Finding code in this repository

You have codemem's `search_code` (an MCP tool). It ranks this repository's functions and classes by what a query means, not only by exact words.

**When to call `search_code`:**
- **At the start**, when the task does not give you an exact identifier, file path or error message to look for. Describe in plain words the code that most likely has to change, for example "parse a glob pattern into its base directory", and use k=5.
- **When Grep has not found it after two tries.** Do not keep trying new patterns: describe the code to `search_code` instead.

**When not to call it:**
- The task names an exact function, class, file or error string: Grep or Read for it directly.
- You can already see the code that has to change: edit it. Do not search again just to confirm.

A result is a preview with its file and lines: Read the file there before you edit.
