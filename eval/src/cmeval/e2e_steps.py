"""What the agent did in a run: searches, views and edits, read from its stream of events.

Claude Code has no search tool of its own. It searches, reads and often edits files through its Bash tool, so
the counts must read shell commands. This module has three parts:

  split_commands  splits the text of one Bash call into simple commands
  classify        gives one simple command a kind (a search, a view, an edit, a test, ...) and its files
  count_steps     walks the events of a run in order and counts what the main agent did, turn by turn

The rules are heuristics. They read what the agent wrote, not what the shell did: a command that ran and
failed counts like one that worked. A call that Claude Code did not run (its result is a <tool_use_error>, for
example "Blocked: sleep 100 followed by ...") counts in tool_calls, bash_calls and blocked_calls, and nothing in it
counts as done. STEPS_VERSION goes up when a rule changes, and `cmeval e2e recount` computes the counts of old
runs again from their streams. The record keeps the version that made its counts in steps_version.

The kinds of an action:

  search_content  grep, egrep, fgrep, rg, ag, ack, git grep (and the Grep tool of older Claude Code versions)
  search_files    find, fd, ls, tree, git ls-files, locate, rg --files (and the Glob tool)
  view            cat, head, tail, sed -n, less, more, nl, bat, awk that only prints, wc, git show REV:PATH,
                  git blame (and the Read tool)
  view_git        git diff, git show REV, git log -p: changes, not files. Kept apart from view
  edit            sed -i, perl -i, tee, patch, git apply, mv, cp, rm, touch, mkdir, and a command whose output
                  goes to a file with > or >> (and Edit, Write, NotebookEdit)
  edit_script     python, node, perl or ruby with an inline script that writes a file. Its targets are a guess
  revert          git checkout PATH, git restore PATH, and git show REV:PATH > PATH: the file goes back to the
                  version in git. Not an edit
  read_outside    a view or a search whose files are all outside the repo: a log in /tmp, a task output file
                  of a command in the background, a cache folder
  write_outside   an edit whose files are all outside the repo: a script or a backup in /tmp
  test            pytest, python -m pytest, tox, npm test, npx playwright test, make test, cargo test, go test
  run             other python, node, npm, make and build commands, and a script that the agent wrote
  git             other git commands
  filter          grep, head, sed and others that read the output of a pipe, not a file
  mcp             a tool of an MCP server (names that start with mcp__)
  other           everything else (echo, cd, true, sleep, ...), and a view or a search of /dev/null only
  unparsed        a command that the reader cannot split

The counts, one line each (all of the main agent; the repo is the folder /testbed):

  search          an action of kind search_content (searches.content) or search_files (searches.files)
  view            an action of kind view (views.count); a file of the repo that it shows is in views.files_viewed
  edit            an action that writes a file of the repo: an edit or edit_script with a repo path, a file
                  written by > or >>, or an edit whose files are not known (git apply). edits.outside counts
                  write_outside actions, edits.reverts counts revert actions; neither is an edit
  surfaced        first turn in which the file reaches the agent: a tool result shows its path (also relative
                  to the shell's folder, or its name in a listing of its folder), or the agent views it or
                  greps inside it by name
  opened          first turn with a view of the file (Read, cat, sed -n, head, ...)
  edited          first turn with an edit of the file (an Edit whose old text was not found counts)
  named_by_agent  first turn in which the agent wrote the path in a tool call

Changes in version 3 (the field names stay; these fields mean something else than in version 2):

  actions         has the kinds revert, read_outside and write_outside. edit, search_content, search_files and
                  view lose those actions; view and search_content of /dev/null only are now other
  searches        counts searches in the repo only. A grep in a log in /tmp is read_outside
  views.count     counts views of repo files only (and views whose file is not known)
  edits.shell     no longer counts git checkout and git restore (they are in edits.reverts)
  gold surfaced   is never later than opened. Version 2 read only the path in the result text, and a grep in
                  one file prints no path
  blocked calls   do not count as actions. New fields: blocked_calls, edits.reverts, and "blocked" in commands
"""

from __future__ import annotations

import fnmatch
import json
import posixpath
import re
import shlex
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

# Raise this number whenever a rule of this module changes. Version 1 was the count_steps of e2e_run, which
# read only the Read tool and the first word of each shell command.
STEPS_VERSION = 3
REPO_ROOT = "/testbed"
MAX_COMMAND_CHARS = 2000
MAX_DEPTH = 8
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
MCP_PREFIX = "mcp__"
CODEMEM_PREFIX = "mcp__codemem__"
KINDS = ("search_content", "search_files", "view", "view_git", "edit", "edit_script", "revert", "read_outside",
         "write_outside", "test", "run", "git", "filter", "mcp", "other", "unparsed")
# Claude Code's Bash tool keeps the working folder of the main agent from one call to the next when the folder
# is inside the project; outside it, the next call starts in the project again. A subagent's calls start in the
# project each time. This is how the tool describes itself. The two transcripts we studied have no cd at all.
CD_PERSISTS = True


# ---- reading shell commands

@dataclass(frozen=True)
class Redirect:
    op: str  # >, >>, <, <<<, <<, >&, <&, <>
    target: str  # a file, a file descriptor (the 1 of 2>&1), a here-string, or a heredoc delimiter
    fd: str = ""  # the file descriptor before the operator (the 2 of 2>&1), or & for &>

    @property
    def writes_file(self) -> bool:
        if self.op == ">&":  # >&1 copies a descriptor; >&file is the same as &>file
            return not (self.target.isdigit() or self.target == "-")
        return self.op in (">", ">>") and not self.target.startswith("/dev/")

    @property
    def hides_output(self) -> bool:
        """True when the command's standard output goes to a file, so the agent does not see it."""
        return self.writes_file and self.fd in ("", "1", "&")


@dataclass(frozen=True)
class SimpleCommand:
    text: str  # the text of the command, without its heredoc body
    words: tuple[str, ...] = ()  # without assignments, wrappers and redirections; words[0] is the program
    redirects: tuple[Redirect, ...] = ()
    piped_in: bool = False  # its input is the output of the command before it (|)
    piped_out: bool = False  # its output goes to the command after it (|)
    heredoc: str | None = None
    nested: bool = False  # it is inside $(...), backticks, <(...), bash -c or find -exec
    via_xargs: bool = False  # xargs gives it more words from its input
    kind: str = "simple"  # or "unparsed"

    @property
    def program(self) -> str:
        return posixpath.basename(self.words[0]) if self.words else ""

    @property
    def args(self) -> tuple[str, ...]:
        return self.words[1:]


class _Unclosed(Exception):
    """A quote, substitution or brace that does not close."""


@dataclass
class _Sub:
    start: int  # positions in the text that holds it
    end: int
    inner: str
    commands: bool  # False for $((...)) and ${...}: nothing in it is a command


@dataclass
class _Piece:
    start: int
    end: int = 0
    op_after: str = ""
    piped_in: bool = False
    subs: list[_Sub] = field(default_factory=list)
    heredocs: list[str] = field(default_factory=list)


_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
_KEYWORDS = {"!", "{", "}", "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "esac"}
_REDIRECT = re.compile(r"(\d+|&)?(>>|>\||>&|>|<<<|<<-|<<|<&|<>|<)")
_WORD_END = set(" \t\n;&|()<>")


def _skip_single(text: str, i: int) -> int:
    end = text.find("'", i + 1)
    if end < 0:
        raise _Unclosed("'")
    return end + 1


def _skip_backtick(text: str, i: int, subs: list[_Sub] | None) -> int:
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == "`":
            if subs is not None:
                subs.append(_Sub(i, j + 1, text[i + 1:j], True))
            return j + 1
        j += 1
    raise _Unclosed("`")


def _match_close(text: str, i: int, open_char: str, close_char: str) -> int:
    """The position of the bracket that closes the one at text[i]. Quotes inside are skipped."""
    depth = 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "'" and open_char == "(":
            i = _skip_single(text, i)
            continue
        if c == '"':
            i = _skip_double(text, i, None)
            continue
        if c == "`":
            i = _skip_backtick(text, i, None)
            continue
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise _Unclosed(open_char)


def _skip_dollar(text: str, i: int, subs: list[_Sub] | None) -> int:
    """Skip $(...), $((...)), ${...}, <(...) or >(...) that starts at text[i]. Records it in subs."""
    open_char = text[i + 1]
    close = _match_close(text, i + 1, open_char, ")" if open_char == "(" else "}")
    if subs is not None:
        arithmetic = text.startswith("$((", i) and text[close - 1] == ")"
        inner = text[i + 2:close]
        subs.append(_Sub(i, close + 1, inner, open_char == "(" and not arithmetic))
    return close + 1


def _skip_double(text: str, i: int, subs: list[_Sub] | None) -> int:
    j = i + 1
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
        elif c == '"':
            return j + 1
        elif c == "`":
            j = _skip_backtick(text, j, subs)
        elif c == "$" and text[j + 1:j + 2] in ("(", "{"):
            j = _skip_dollar(text, j, subs)
        else:
            j += 1
    raise _Unclosed('"')


def _skip_quoted(text: str, i: int, subs: list[_Sub] | None) -> int | None:
    """If a quote or a substitution starts at text[i], the position after it; else None."""
    c = text[i]
    if c == "'":
        return _skip_single(text, i)
    if c == '"':
        return _skip_double(text, i, subs)
    if c == "`":
        return _skip_backtick(text, i, subs)
    if c in "$<>" and text[i + 1:i + 2] == "(" or c == "$" and text[i + 1:i + 2] == "{":
        return _skip_dollar(text, i, subs)
    return None


def _heredoc_delimiter(text: str, i: int) -> tuple[str, bool, int]:
    """Read the operator << or <<- at text[i] and its delimiter word. Returns the delimiter, whether leading
    tabs are stripped, and the position after the word."""
    j = i + 2
    strip = text[j:j + 1] == "-"
    j += strip
    while j < len(text) and text[j] in " \t":
        j += 1
    word = []
    while j < len(text) and text[j] not in _WORD_END:
        if text[j] in "'\"":
            close = text.find(text[j], j + 1)
            close = len(text) if close < 0 else close
            word.append(text[j + 1:close])
            j = close + 1
        elif text[j] == "\\":
            word.append(text[j + 1:j + 2])
            j += 2
        else:
            word.append(text[j])
            j += 1
    return "".join(word), strip, j


def _read_heredoc(text: str, i: int, delimiter: str, strip: bool) -> tuple[str, int]:
    """The body of a heredoc that starts at text[i], and the position after its closing line. A body without
    a closing line runs to the end, as in bash."""
    lines, j = [], i
    while j < len(text):
        end = text.find("\n", j)
        end = len(text) if end < 0 else end
        line = text[j:end]
        if (line.lstrip("\t") if strip else line).rstrip() == delimiter:
            return "\n".join(lines), end + 1
        lines.append(line)
        j = end + 1
    return "\n".join(lines), len(text)


def _scan(text: str) -> tuple[list[_Piece], int | None]:
    """Cut the text at the shell's control operators. Returns the pieces, and the position where a quote or
    substitution does not close (None when the whole text was read)."""
    pieces: list[_Piece] = []
    pending: list[tuple[_Piece, str, bool]] = []  # heredocs whose body starts after the next line end
    cur = _Piece(0)
    pipe = False
    i, n = 0, len(text)
    comment_at = None

    def finish(end: int, op: str) -> None:
        nonlocal cur, pipe, comment_at
        cur.end = comment_at if comment_at is not None else end
        cur.op_after = op
        if text[cur.start:cur.end].strip():
            cur.piped_in = pipe
            pieces.append(cur)
            pipe = op in ("|", "|&")
        elif op in (";", "&&", "||", "&", ")"):
            pipe = False  # an empty piece before "(" or a line end keeps a pipe: `a | (b)`, `a |<newline>b`
        cur = _Piece(end + len(op))
        comment_at = None

    while i < n:
        c = text[i]
        if comment_at is not None and c != "\n":
            i += 1
            continue
        try:
            after = _skip_quoted(text, i, cur.subs)
        except _Unclosed:
            return pieces, cur.start
        if after is not None:
            i = after
            continue
        if c == "\\":
            i += 2
            continue
        if c == "#" and (i == cur.start or text[i - 1] in " \t\n;&|()"):
            comment_at = i
            continue
        if text.startswith("<<", i) and not text.startswith("<<<", i):
            delimiter, strip, i = _heredoc_delimiter(text, i)
            pending.append((cur, delimiter, strip))
            continue
        if c == "\n":
            finish(i, "\n")
            i += 1
            for owner, delimiter, strip in pending:
                body, i = _read_heredoc(text, i, delimiter, strip)
                owner.heredocs.append(body)
            pending.clear()
            cur.start = i
            continue
        op = next((o for o in ("&&", "||", "|&", ";;", ";", "|", "(", ")") if text.startswith(o, i)), None)
        if op is None and c == "&" and text[i + 1:i + 2] != ">" and (i == 0 or text[i - 1] not in "<>"):
            op = "&"
        if op:
            finish(i, op)
            i += len(op)
            continue
        i += 1
    finish(n, "")
    for owner, _, _ in pending:  # a heredoc operator on the last line: the body is empty
        owner.heredocs.append("")
    return pieces, None


def _cut_redirects(text: str) -> tuple[str, list[Redirect]]:
    """Take the redirections out of the text of one command (its substitutions are already masked)."""
    out, redirects = [], []
    i, n, word_start = 0, len(text), True
    while i < n:
        c = text[i]
        if c in " \t\n":
            out.append(c)
            word_start, i = True, i + 1
            continue
        after = _skip_quoted(text, i, None) if c in "'\"`" else None
        if after is not None or c == "\\":
            after = after if after is not None else i + 2
            out.append(text[i:after])
            word_start, i = False, after
            continue
        m = _REDIRECT.match(text, i) if (word_start or c in "<>") else None
        if m and not (m.group(1) and not word_start):
            j = m.end()
            while j < n and text[j] in " \t":
                j += 1
            k = j
            while k < n and text[k] not in " \t\n<>":
                if text[k] in "'\"":
                    k = _skip_quoted(text, k, None)
                elif text[k] == "\\":
                    k += 2
                else:
                    k += 1
            op = {">|": ">"}.get(m.group(2), m.group(2))
            if op == "<<-":
                op = "<<"
            redirects.append(Redirect(op, _unquote(text[j:k]), m.group(1) or ""))
            out.append(" ")
            word_start, i = True, k
            continue
        out.append(c)
        word_start, i = False, i + 1
    return "".join(out), redirects


def _unquote(word: str) -> str:
    try:
        parts = shlex.split(word)
    except ValueError:
        return word
    return " ".join(parts)


def _split_words(text: str) -> list[str]:
    text = text.replace("\\\n", " ")
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


def _skip_options(words: list[str], with_value: set[str]) -> list[str]:
    """Drop the leading options of a wrapper. An option in with_value takes the next word as its value."""
    while words and words[0].startswith("-") and words[0] != "-":
        if words[0] == "--":
            return words[1:]
        words = words[2:] if words[0] in with_value else words[1:]
    return words


_WRAPPERS = {
    "timeout": {"-k", "-s", "--kill-after", "--signal"},
    "time": {"-f", "-o", "--format", "--output"},
    "env": {"-u", "-C", "-S", "--unset", "--chdir", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p"},
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T"},
    "xargs": {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "--max-args", "--max-procs", "--delimiter",
              "--arg-file", "--max-lines"},
    "command": set(),
    "stdbuf": {"-i", "-o", "-e"},
    "nohup": set(),
    "exec": {"-a"},
}


def _unwrap(words: list[str]) -> tuple[list[str], bool]:
    """Remove VAR=value words and wrappers (timeout 60, env, xargs, ...). Returns the words and whether xargs
    was one of the wrappers."""
    via_xargs = False
    for _ in range(MAX_DEPTH):
        while words and words[0] in _KEYWORDS:
            words = words[1:]
        while words and _ASSIGNMENT.match(words[0]):
            words = words[1:]
        name = posixpath.basename(words[0]) if words else ""
        if name not in _WRAPPERS or (name == "command" and words[1:2] in (["-v"], ["-V"])):
            break
        rest = _skip_options(words[1:], _WRAPPERS[name])
        if name == "timeout" and rest and re.fullmatch(r"[\d.]+[smhd]?", rest[0]):
            rest = rest[1:]
        if name == "nice" and rest and re.fullmatch(r"-?\d+", rest[0]):
            rest = rest[1:]
        if not rest:  # `time` alone, or xargs that runs echo
            break
        via_xargs = via_xargs or name == "xargs"
        words = rest
    return words, via_xargs


_PLACEHOLDER = re.compile("\x00(\\d+)\x00")


def _commands_of_piece(text: str, piece: _Piece, depth: int) -> list[SimpleCommand]:
    """The simple command of one piece, then the commands of bash -c, find -exec and its substitutions."""
    raw = text[piece.start:piece.end]
    subs = sorted(piece.subs, key=lambda s: s.start)
    masked, last = [], piece.start
    for k, sub in enumerate(subs):
        masked.append(text[last:sub.start] + f"\x00{k}\x00")
        last = sub.end
    masked.append(text[last:piece.end])
    rest, redirects = _cut_redirects("".join(masked))

    def restore(word: str) -> str:
        def original(m: re.Match) -> str:
            sub = subs[int(m.group(1))]
            return text[sub.start:sub.end]
        return _PLACEHOLDER.sub(original, word)

    words, via_xargs = _unwrap([restore(w) for w in _split_words(rest)])
    redirects = [replace(r, target=restore(r.target)) for r in redirects]
    found: list[SimpleCommand] = []
    heredoc = "\n".join(piece.heredocs) if piece.heredocs else None
    program = posixpath.basename(words[0]) if words else ""
    script = _shell_script(program, words)
    if words and script is None:
        found.append(SimpleCommand(raw.strip(), tuple(words), tuple(redirects), piece.piped_in,
                                   piece.op_after in ("|", "|&"), heredoc, False, via_xargs))
    elif script is not None:
        found += [replace(c, nested=True) for c in split_commands(script, _depth=depth + 1)]
    if program == "find":
        found += _find_exec(words, depth)
    for sub in subs:
        if sub.commands:
            found += [replace(c, nested=True) for c in split_commands(sub.inner, _depth=depth + 1)]
    return found


def _shell_script(program: str, words: list[str]) -> str | None:
    """The script of `bash -c SCRIPT` (or sh, zsh, dash), or None."""
    if program not in ("bash", "sh", "zsh", "dash"):
        return None
    for k, word in enumerate(words[1:-1], start=1):
        if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", word):
            return words[k + 1]
        if not word.startswith("-"):
            return None
    return None


def _find_exec(words: list[str], depth: int) -> list[SimpleCommand]:
    """The commands that find runs with -exec, -execdir, -ok or -okdir."""
    found = []
    i = 0
    while i < len(words):
        if words[i] in ("-exec", "-execdir", "-ok", "-okdir"):
            j = i + 1
            while j < len(words) and words[j] not in (";", "+"):
                j += 1
            inner, _ = _unwrap(words[i + 1:j])
            if inner:
                found.append(SimpleCommand(" ".join(inner), tuple(inner), nested=True))
            i = j
        i += 1
    return found


def split_commands(command: str, _depth: int = 0) -> list[SimpleCommand]:
    """The simple commands of one Bash call, in order. The commands inside a substitution come after the
    command that holds it, marked nested. Never raises: text that cannot be read becomes one command of kind
    unparsed."""
    if _depth > MAX_DEPTH:
        return [SimpleCommand(command.strip(), tuple(command.split()), kind="unparsed")]
    try:
        pieces, unclosed_at = _scan(command)
        found: list[SimpleCommand] = []
        for piece in pieces:
            found += _commands_of_piece(command, piece, _depth)
        if unclosed_at is not None and command[unclosed_at:].strip():
            tail = command[unclosed_at:].strip()
            found.append(SimpleCommand(tail, tuple(tail.split()), kind="unparsed"))
        return found
    except Exception:  # noqa: BLE001 - a reader of agent text must never stop a run's record
        return [SimpleCommand(command.strip(), tuple(command.split()), kind="unparsed")]


# ---- what a command does

@dataclass(frozen=True)
class Action:
    kind: str
    program: str = ""
    paths: tuple[str, ...] = ()  # repo paths, relative to the repo root ("." is the root)
    outside: tuple[str, ...] = ()  # paths outside the repo, absolute
    pattern: str | None = None
    recursive: bool = False
    first_line: int | None = None
    last_line: int | None = None
    lines: int | None = None  # the lines shown, when the command says how many
    whole_file: bool = False
    writes: tuple[str, ...] = ()  # repo files that a redirection (> or >>) writes, for any kind
    writes_outside: tuple[str, ...] = ()
    guess: bool = False  # the paths of an edit_script are quoted strings of the script: a guess
    shows_output: bool = True  # the output reaches the tool result: no pipe, no redirection to a file


@dataclass(frozen=True)
class _Where:
    cwd: str  # absolute
    root: str  # absolute, without a trailing slash

    def split(self, words) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Repo paths and outside paths of the words that are paths. Words with $ or a substitution are not."""
        inside, outside = [], []
        for word in words:
            path, out = self.norm(word)
            if path is None:
                continue
            target = outside if out else inside
            if path not in target:
                target.append(path)
        return tuple(inside), tuple(outside)

    def norm(self, word: str) -> tuple[str | None, bool]:
        """The repo path of a word and False, or the absolute path and True when it is outside the repo. None
        when the word is not a path that can be known."""
        if word.startswith("~"):
            return word, True
        if not word or word in ("-", "{}") or any(ch in word for ch in "$`\x00\n"):
            return None, False
        full = posixpath.normpath(word if word.startswith("/") else posixpath.join(self.cwd, word))
        if full == self.root:
            return ".", False
        if full.startswith(self.root + "/"):
            return full[len(self.root) + 1:], False
        return full, True

    def resolve(self, word: str) -> str:
        return posixpath.normpath(word if word.startswith("/") else posixpath.join(self.cwd, word))


def _parse(args, short_value: str = "", long_value: tuple[str, ...] = ()) -> tuple[dict[str, list], list[str]]:
    """Split GNU-style arguments into options and other words. An option may come after other words; `--`
    ends the options. Returns a dict from each option ("-n", "--include") to its values (None for a flag)."""
    opts: dict[str, list] = {}
    words: list[str] = []
    args = list(args)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            words += args[i + 1:]
            break
        if a.startswith("--") and len(a) > 2:
            name, eq, value = a.partition("=")
            if not eq and name in long_value:
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            opts.setdefault(name, []).append(value if (eq or name in long_value) else None)
        elif a.startswith("-") and len(a) > 1:
            for j, ch in enumerate(a[1:], start=1):
                if ch in short_value:
                    value = a[j + 1:]
                    if not value:
                        value = args[i + 1] if i + 1 < len(args) else ""
                        i += 1
                    opts.setdefault("-" + ch, []).append(value)
                    break
                opts.setdefault("-" + ch, []).append(None)
        else:
            words.append(a)
        i += 1
    return opts, words


def _looks_like_folder(path: str) -> bool:
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return path.endswith("/") or last in (".", "..", "") or "." not in last


def _pathish(word: str) -> bool:
    """A word that looks like a file or folder path (a heuristic for words whose role is not known)."""
    if not word or word.startswith("-") or "://" in word or "=" in word or " " in word:
        return False
    return word in (".", "..") or "/" in word or bool(re.search(r"\.[A-Za-z0-9]{1,8}$", word))


_SEARCH_VALUE = {
    "grep": ("efmABCdD", ("--regexp", "--file", "--max-count", "--after-context", "--before-context", "--context",
                          "--include", "--exclude", "--exclude-dir", "--exclude-from", "--label", "--binary-files",
                          "--devices", "--directories", "--group-separator")),
    "rg": ("efgtTmABCjMrEd", ("--regexp", "--file", "--glob", "--iglob", "--type", "--type-not", "--max-count",
                              "--max-depth", "--replace", "--context", "--after-context", "--before-context",
                              "--threads", "--encoding", "--max-columns", "--sort", "--sortr", "--type-add",
                              "--ignore-file", "--max-filesize", "--colors", "--path-separator",
                              "--context-separator")),
    "ag": ("ABCGgmp", ("--ignore", "--ignore-dir", "--file-search-regex", "--max-count", "--context", "--depth")),
    "ack": ("ABCmg", ("--type", "--ignore-dir", "--match", "--max-count", "--context")),
    "git grep": ("efABCmO", ("--max-depth", "--threads", "--open-files-in-pager", "--context", "--max-count")),
}


def _search(cmd: SimpleCommand, program: str, args, where: _Where) -> Action:
    family = "grep" if program in ("grep", "egrep", "fgrep", "zgrep") else program
    short_value, long_value = _SEARCH_VALUE[family]
    opts, words = _parse(args, short_value, long_value)
    if (program == "rg" and "--files" in opts) or (program == "ag" and "-g" in opts) \
            or (program == "ack" and ("-f" in opts or "-g" in opts)):
        paths, outside = where.split(words)  # the pattern of -g is the option's value
        return Action("search_files", f"{program} --files" if program == "rg" else program, paths, outside,
                      recursive=True)
    given = opts.get("-e") or opts.get("--regexp") or opts.get("-f") or opts.get("--file")
    pattern = given[0] if given else (words[0] if words else None)
    targets = words if given else words[1:]
    paths, outside = where.split(targets)
    recursive = (family != "grep" or bool({"-r", "-R", "--recursive", "--dereference-recursive"} & set(opts))
                 or "recurse" in (opts.get("-d", []) + opts.get("--directories", []))
                 or any(_looks_like_folder(p) for p in paths + outside))
    if family in ("grep", "rg", "ag", "ack") and cmd.piped_in and not targets and not cmd.via_xargs \
            and not (family == "grep" and recursive):
        return Action("filter", program, pattern=pattern)
    return Action("search_content", program, paths, outside, pattern=pattern, recursive=recursive)


_FILE_LIST_VALUE = {
    "fd": ("etEdxXcSj", ("--extension", "--type", "--exclude", "--max-depth", "--exec", "--exec-batch", "--size")),
    "ls": ("IwT", ("--ignore", "--width", "--hide", "--sort", "--format", "--time", "--color")),
    "tree": ("LIPo", ("--filelimit", "--charset")),
    "locate": ("dln", ("--database", "--limit")),
}


def _find(args, where: _Where) -> Action:
    """find [options] [folders] [expression]: the folders come before the first word of the expression."""
    i, folders = 0, []
    while i < len(args) and (args[i] in ("-H", "-L", "-P", "-D") or args[i].startswith("-O")):
        i += 2 if args[i] == "-D" else 1
    while i < len(args) and not args[i].startswith(("-", "(", "!", ")")):
        folders.append(args[i])
        i += 1
    pattern = None
    for k in range(i, len(args) - 1):
        if args[k] in ("-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-wholename"):
            pattern = args[k + 1]
            break
    paths, outside = where.split(folders)
    if "-delete" in args[i:]:
        return Action("edit", "find -delete", paths, outside, pattern=pattern)
    return Action("search_files", "find", paths, outside, pattern=pattern, recursive=True)


def _int(text: str) -> int | None:
    return int(text) if text.isdigit() else None


def _head_tail(cmd: SimpleCommand, program: str, args, where: _Where) -> Action:
    count, start, files, unknown = 10, None, [], False
    i = 0
    while i < len(args):
        a = args[i]
        value = None
        if re.fullmatch(r"-\d+", a):
            value = a[1:]
        elif a in ("-n", "--lines") and i + 1 < len(args):
            value, i = args[i + 1], i + 1
        elif a.startswith("--lines="):
            value = a.split("=", 1)[1]
        elif re.fullmatch(r"-n[+-]?\d+", a):
            value = a[2:]
        elif a in ("-c", "--bytes") or a.startswith(("-c", "--bytes=")):
            unknown = True
            i += a in ("-c", "--bytes")
        elif re.fullmatch(r"\+\d+", a) and program == "tail":
            value = a
        elif a.startswith("-") and a != "-":
            pass  # -q, -v, -f, -F
        else:
            files.append(a)
        if value is not None:
            if value.startswith("+") and program == "tail":
                start = _int(value[1:])
            elif value.startswith("-") or _int(value) is None:
                unknown = True
            else:
                count = int(value)
        i += 1
    kind = "view" if files else "filter" if cmd.piped_in else "other"
    paths, outside = where.split(files)
    if unknown:
        return Action(kind, program, paths, outside)
    if program == "tail" and start is not None:
        return Action(kind, program, paths, outside, first_line=start)
    if program == "head":
        return Action(kind, program, paths, outside, first_line=1, last_line=count, lines=count * max(1, len(files)))
    return Action(kind, program, paths, outside, lines=count * max(1, len(files)))


_SED_RANGE = re.compile(r"\s*(\d+)\s*(?:,\s*(\d+|\$|\+\d+))?\s*p\s*")


def _sed(cmd: SimpleCommand, args, where: _Where) -> Action:
    quiet, in_place, scripts, script_file, words = False, False, [], False, []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            words += args[i + 1:]
            break
        if a.startswith("--"):
            name, _, value = a.partition("=")
            quiet = quiet or name in ("--quiet", "--silent")
            in_place = in_place or name == "--in-place"
            if name == "--expression":
                scripts.append(value)
            script_file = script_file or name == "--file"
        elif a.startswith("-") and len(a) > 1:
            for j, ch in enumerate(a[1:], start=1):
                if ch == "n":
                    quiet = True
                elif ch == "i":
                    in_place = True
                    break  # the rest is the suffix of the backup file
                elif ch in "efl":
                    value = a[j + 1:]
                    if not value and i + 1 < len(args):
                        value, i = args[i + 1], i + 1
                    if ch == "e":
                        scripts.append(value)
                    script_file = script_file or ch == "f"
                    break
        else:
            words.append(a)
        i += 1
    if not scripts and not script_file and words:
        scripts, words = [words[0]], words[1:]
    paths, outside = where.split(words)
    if in_place:
        return Action("edit", "sed -i", paths, outside)
    program = "sed -n" if quiet else "sed"
    kind = "view" if words else "filter" if cmd.piped_in else "other"
    if not quiet:
        return Action(kind, program, paths, outside, whole_file=bool(words))
    ranges = _sed_ranges(";".join(scripts))
    if not ranges:
        return Action(kind, program, paths, outside)
    first = min(r[0] for r in ranges)
    if any(r[1] is None for r in ranges):
        return Action(kind, program, paths, outside, first_line=first)
    lines = sum(max(0, b - a + 1) for a, b in ranges) * max(1, len(words))
    return Action(kind, program, paths, outside, first_line=first, last_line=max(r[1] for r in ranges), lines=lines)


def _sed_ranges(script: str) -> list[tuple[int, int | None]]:
    """The line ranges that a sed -n script prints (`10,40p`, `5p`, `100,$p`, `10,+5p`, joined by ; or line
    ends). An empty list when a part of the script is something else."""
    ranges = []
    for part in re.split(r"[;\n]", script):
        if not part.strip() or re.fullmatch(r"\s*\d*\s*q\s*", part):
            continue
        m = _SED_RANGE.fullmatch(part)
        if not m:
            return []
        first, end = int(m.group(1)), m.group(2)
        if end is None:
            ranges.append((first, first))
        elif end == "$":
            ranges.append((first, None))
        else:
            ranges.append((first, first + int(end[1:]) if end[0] == "+" else int(end)))
    return ranges


_AWK_RANGE = (re.compile(r"NR\s*>=\s*(\d+)\s*&&\s*NR\s*<=\s*(\d+)"),
              re.compile(r"NR\s*==\s*(\d+)\s*,\s*NR\s*==\s*(\d+)"))


def _awk(cmd: SimpleCommand, args, where: _Where) -> Action:
    opts, words = _parse(args, "Fvfi", ("--field-separator", "--assign", "--file", "--include"))
    program_text = None if "-f" in opts or "--file" in opts else (words.pop(0) if words else "")
    paths, outside = where.split(words)
    if "inplace" in opts.get("-i", []):
        return Action("edit", "awk -i", paths, outside)
    if program_text and (re.search(r"print[^;}]*>\s*\S", program_text) or "system(" in program_text):
        return Action("run", "awk", paths, outside)
    if not words:
        return Action("filter" if cmd.piped_in else "other", "awk")
    for pattern in _AWK_RANGE:
        m = pattern.search(program_text or "")
        if m:
            first, last = int(m.group(1)), int(m.group(2))
            return Action("view", "awk", paths, outside, first_line=first, last_line=last,
                          lines=(last - first + 1) * len(words))
    return Action("view", "awk", paths, outside)


_SIMPLE_VIEWS = {"cat", "nl", "less", "more", "bat", "batcat", "tac", "wc", "sort", "uniq", "cut", "column", "jq",
                 "tr", "rev", "strings", "xxd", "od", "hexdump", "diff", "cmp", "file"}
_WHOLE_FILE = {"cat", "nl", "less", "more", "bat", "batcat", "tac", "sort", "rev"}


def _simple_view(cmd: SimpleCommand, program: str, args, where: _Where) -> Action:
    values = {"bat": "rlmH", "batcat": "rlmH", "cut": "dfcb", "sort": "ktoS", "nl": "bivwsn", "jq": "",
              "diff": "UCLx"}.get(program, "")
    opts, words = _parse(args, values)
    if program == "tr":
        words = []  # tr only reads its input
    if program == "jq" and words:
        words = words[1:]  # the filter
    if not words or words == ["-"]:
        if program == "file":
            return Action("other", program)
        return Action("filter" if cmd.piped_in else "other", program)
    paths, outside = where.split(words)
    if program == "file":
        return Action("other", program, paths, outside)
    if program in ("bat", "batcat") and opts.get("-r"):
        m = re.fullmatch(r"(\d+)?:(\d+)?", opts["-r"][0] or "")
        if m and m.group(1) and m.group(2):
            first, last = int(m.group(1)), int(m.group(2))
            return Action("view", program, paths, outside, first_line=first, last_line=last, lines=last - first + 1)
    if program == "wc":
        return Action("view", program, paths, outside, lines=0)
    return Action("view", program, paths, outside, whole_file=program in _WHOLE_FILE)


_GIT_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
_GIT_SUMMARY = {"--stat", "--name-only", "--name-status", "--shortstat", "--numstat", "--summary", "--quiet",
                "--exit-code", "--dirstat", "--check"}
_REV_LIKE = re.compile(r"(HEAD|FETCH_HEAD|ORIG_HEAD|@)([~^]\d*)*|[0-9a-f]{6,40}([~^]\d*)*|\S*\.\.\.?\S*")


def _git(cmd: SimpleCommand, args, where: _Where) -> Action:
    args = list(args)
    while args and args[0].startswith("-"):  # options of git itself
        option = args.pop(0)
        if option in _GIT_VALUE and args:
            value = args.pop(0)
            if option == "-C":
                where = _Where(where.resolve(value), where.root)
    if not args:
        return Action("git", "git")
    sub, rest = args[0], args[1:]
    name = f"git {sub}"
    if sub == "grep":
        return _search(cmd, "git grep", rest, where)
    if sub in ("ls-files", "ls-tree"):
        opts, words = _parse(rest, "xX", ("--exclude", "--exclude-from", "--format"))
        if sub == "ls-tree":
            words = words[1:]  # the tree
        paths, outside = where.split(words)
        return Action("search_files", name, paths, outside, recursive=sub == "ls-files" or "-r" in opts)
    opts, words = _parse(rest, "nL" if sub == "log" else "",
                         ("--source", "--format", "--pretty", "--author", "--since", "--until", "--grep"))
    pathspec = rest[rest.index("--") + 1:] if "--" in rest else []
    if sub == "show":
        files = [w.split(":", 1)[1] for w in words if ":" in w and not w.startswith(":")]
        if files:
            root_where = _Where(where.root, where.root)
            relative = [f for f in files if f.startswith("./") or f.startswith("../")]
            paths, outside = (where if relative else root_where).split(files)
            return Action("view", "git show", paths, outside, whole_file=True)
        kind = "git" if _GIT_SUMMARY & set(opts) else "view_git"
        return Action(kind, name, *where.split(pathspec))
    if sub == "diff":
        kind = "git" if _GIT_SUMMARY & set(opts) else "view_git"
        candidates = pathspec or [w for w in words if not _REV_LIKE.fullmatch(w) and _pathish(w)]
        return Action(kind, name, *where.split(candidates))
    if sub == "log":
        kind = "view_git" if {"-p", "-u", "--patch", "-L"} & set(opts) else "git"
        return Action(kind, name, *where.split(pathspec))
    if sub == "blame":
        files = pathspec or words[-1:]
        return Action("view", name, *where.split(files), whole_file=not ({"-L"} & set(opts)))
    if sub == "checkout":
        targets = pathspec or [w for w in words if w == "." or (_pathish(w) and not _REV_LIKE.fullmatch(w))]
        if targets:
            return Action("revert", name, *where.split(targets))
        return Action("git", name)
    if sub == "restore":
        if ("--staged" in opts or "-S" in opts) and not ({"--worktree", "-W"} & set(opts)):
            return Action("git", name)
        return Action("revert", name, *where.split(pathspec or words))
    if sub == "apply":
        if {"--check", "--stat", "--numstat", "--summary"} & set(opts):
            return Action("git", name)
        return Action("edit", name)  # the files that the patch changes are not known
    return Action("git", name)


def _file_ops(program: str, args, where: _Where) -> Action:
    opts, words = _parse(args, "tSm" if program in ("cp", "mv", "ln", "install") else "s" if program == "truncate"
                         else "m" if program == "mkdir" else "")
    if program in ("cp", "ln", "install"):
        target = opts.get("-t", [None])[0]
        if target is None and words:
            target, sources = words[-1], words[:-1]
        else:
            sources = words
        targets = [target] if target else []
        if target and sources and (target in (".", "..") or target.endswith("/")
                                   or (_looks_like_folder(target) and "." in posixpath.basename(sources[0]))):
            targets = [posixpath.join(target, posixpath.basename(s)) for s in sources]
        words = targets
    return Action("edit", program, *where.split(words))


_TESTERS = {"pytest", "py.test", "tox", "nox"}
_RUNNERS = {"python", "python3", "node", "npm", "npx", "yarn", "pnpm", "make", "cargo", "go", "gcc", "g++", "cc",
            "clang", "cmake", "ninja", "mvn", "gradle", "javac", "java", "tsc", "ruff", "black", "isort", "flake8",
            "mypy", "pylint", "pre-commit", "pip", "pip3", "uv", "poetry", "conda", "rustc", "meson", "deno", "bun",
            "ruby", "perl", "bash", "sh", "zsh", "pyright", "eslint", "prettier", "asv", "cython", "setup.py"}
_WRITES = re.compile(
    r"""open\s*\([^\n]{0,200}?,\s*(?:mode\s*=\s*)?['"](?:w|a|x|r\+|w\+|a\+|[wax]b|[wax]t)['"]"""
    r"|\.write_(?:text|bytes)\s*\(|writeFileSync|appendFileSync|\bwriteFile\s*\(|File\.write|IO\.write"
    r"|shutil\.(?:copy\w*|move)\s*\(|os\.(?:remove|rename|replace|unlink)\s*\(|\.unlink\s*\("
    r"""|open\s*\(?\s*(?:my\s+)?\$?\w+\s*,\s*['"]\+?>""")
_QUOTED_PATH = re.compile(r"""['"]([^'"\s]{1,300})['"]""")


def _python_args(args: list[str]) -> tuple[str | None, str | None, list[str]]:
    """Python's own options end at -c, -m or the script. Returns the -c script, the -m module, and the words
    after them (the script file first, when there is one)."""
    while args:
        a = args.pop(0)
        if a.startswith("-c") or a.startswith("-m"):
            value = a[2:] or (args.pop(0) if args else "")
            return (value, None, args) if a[1] == "c" else (None, value, args)
        if a in ("-W", "-X"):
            args = args[1:]
        elif not a.startswith("-") or a == "-":
            return None, None, [a] + args
    return None, None, []


def _test_paths(args) -> list[str]:
    """The test files and folders of a test command, without the ::name of a test."""
    return [w.split("::")[0] for w in args if _pathish(w.split("::")[0])]


def _python_like(cmd: SimpleCommand, program: str, args, where: _Where) -> Action:
    family = "python" if program.startswith("python") or program == "pypy3" else program
    script = None
    if family == "python":
        script, module, words = _python_args(list(args))
        if module is not None:
            if module in ("pytest", "py.test", "unittest", "tox", "nox"):
                return Action("test", f"python -m {module}", *where.split(_test_paths(words)))
            return Action("run", f"python -m {module}")
    else:
        short = {"perl": "eIMx", "ruby": "eIr", "node": "ep"}.get(family, "e")
        opts, words = _parse(args, short, ("--eval", "--print", "--require"))
        if family == "perl" and "-i" in opts:
            return Action("edit", "perl -i", *where.split(words))
        script = (opts.get("-e") or opts.get("--eval") or opts.get("-p") or [None])[0]
    if script is None and cmd.heredoc is not None and (not words or words[0] == "-"):
        script = cmd.heredoc
    if script is not None:
        if _WRITES.search(script):
            targets = [m.group(1) for m in _QUOTED_PATH.finditer(script) if _pathish(m.group(1))
                       and not re.fullmatch(r"[rwaxbt+]{1,3}", m.group(1))]
            paths, outside = where.split(targets)
            return Action("edit_script", family, paths, outside, guess=True)
        return Action("run", family)
    return Action("run", family, *where.split(words[:1]))


def _is_test(program: str, args) -> bool:
    words = [a for a in args if not a.startswith("-")]
    if program in _TESTERS:
        return True
    if program in ("npm", "yarn", "pnpm", "bun"):
        return bool(words) and (words[0] in ("test", "t") or (words[0] == "run" and "test" in " ".join(words[1:2])))
    if program == "npx":
        return bool(words) and (words[0] in ("jest", "vitest", "mocha") or words[:2] == ["playwright", "test"])
    if program == "make":
        return any("test" in w or w == "check" for w in words if "=" not in w)
    if program in ("cargo", "go"):
        return bool(words) and words[0] == "test"
    return False


_FILTERS = {"xargs", "tee"}
_OTHER = {"echo", "printf", "cd", "pushd", "popd", "true", "false", "sleep", "pwd", "export", "set", "unset",
          "source", ".", "which", "type", "exit", "return", "date", "[", "[[", "test", ":", "for", "case", "wait",
          "kill", "realpath", "dirname", "basename", "readlink", "stat", "du", "df", "id", "whoami", "uname",
          "hostname", "env", "printenv", "alias", "local", "declare", "read", "shift", "trap", "ulimit", "umask",
          "chmod", "chown", "seq", "yes", "history", "jobs", "fg", "bg", "disown", "clear", "nproc", "free", "ps"}


def classify(cmd: SimpleCommand, cwd: str | None = None, repo_root: str = REPO_ROOT) -> Action:
    """The kind of one simple command, and the files it touches. `cwd` is the shell's folder (absolute; the
    repo root when None). A file redirection (> or >>) turns a view, filter, git or other command into an edit;
    other kinds keep their kind and list the written files in `writes`."""
    root = repo_root.rstrip("/") or "/"
    where = _Where(cwd or root, root)
    if cmd.kind == "unparsed":
        return Action("unparsed", cmd.program)
    try:
        action = _classify(cmd, where)
    except Exception:  # noqa: BLE001 - a heuristic must never stop a run's record
        return Action("unparsed", cmd.program)
    written = [r.target for r in cmd.redirects if r.writes_file]
    hides = any(r.hides_output for r in cmd.redirects)
    shows = not (cmd.piped_out or cmd.nested or hides)
    if written:
        writes, writes_outside = where.split(written)
        if action.program == "git show" and action.kind == "view" and writes and set(writes) <= set(action.paths):
            return Action("revert", "git show", writes, shows_output=False)  # git show HEAD:a.py > a.py
        if action.kind in ("view", "view_git", "filter", "other", "git"):
            return _place(Action("edit", cmd.program, writes, writes_outside, shows_output=False), where)
        action = replace(action, writes=writes, writes_outside=writes_outside)
    action = _place(action, where)
    return replace(action, shows_output=shows) if action.shows_output != shows else action


def _holds_repo(path: str, root: str) -> bool:
    """True when an absolute path outside the repo is a folder that holds the repo (/ for the root /testbed)."""
    return path.startswith("/") and (root + "/").startswith(path.rstrip("/") + "/")


def _place(action: Action, where: _Where) -> Action:
    """Move a view, search or edit whose files are all outside the repo to read_outside or write_outside.
    /dev/null and other /dev/ files are not files: a view or search of only them is `other`."""
    if action.kind in ("view", "search_content", "search_files"):
        outside = tuple(p for p in action.outside if not p.startswith("/dev/"))
        if outside != action.outside:
            if not action.paths and not outside:
                return Action("other", action.program, shows_output=action.shows_output)
            action = replace(action, outside=outside)
        # A search without a target looks in the shell's folder.
        places = outside or ((where.cwd,) if action.kind != "view" and where.norm(where.cwd)[1] else ())
        if not action.paths and places and not any(_holds_repo(p, where.root) for p in places):
            return replace(action, kind="read_outside", first_line=None, last_line=None, lines=None,
                           whole_file=False, recursive=False)
    elif action.kind in ("edit", "edit_script") and not action.paths and not action.writes and action.outside \
            and not any(_holds_repo(p, where.root) for p in action.outside):
        return replace(action, kind="write_outside")
    return action


def _classify(cmd: SimpleCommand, where: _Where) -> Action:
    program, args = cmd.program, cmd.args
    if not program:
        return Action("other")
    if program in ("grep", "egrep", "fgrep", "zgrep", "rg", "ag", "ack"):
        return _search(cmd, program, args, where)
    if program == "git":
        return _git(cmd, args, where)
    if program == "find":
        return _find(args, where)
    if program in ("fd", "fdfind", "ls", "tree", "locate"):
        short, long_value = _FILE_LIST_VALUE.get("fd" if program == "fdfind" else program, ("", ()))
        opts, words = _parse(args, short, long_value)
        if program in ("fd", "fdfind", "locate") and words:
            words = words[1:]  # the pattern
        paths, outside = where.split(words)
        return Action("search_files", program, paths, outside, recursive=program in ("fd", "fdfind", "tree")
                      or "-R" in opts or "--recursive" in opts)
    if program in ("head", "tail"):
        return _head_tail(cmd, program, args, where)
    if program == "sed":
        return _sed(cmd, args, where)
    if program in ("awk", "gawk", "mawk"):
        return _awk(cmd, args, where)
    if program in _SIMPLE_VIEWS:
        return _simple_view(cmd, program, args, where)
    if program in ("mv", "cp", "rm", "touch", "mkdir", "rmdir", "ln", "install", "truncate"):
        return _file_ops(program, args, where)
    if program == "tee":
        _, words = _parse(args)
        if not words:
            return Action("filter" if cmd.piped_in else "other", program)
        return Action("edit", program, *where.split(words))
    if program == "patch":
        opts, words = _parse(args, "pidoBrDFVYzg", ("--input", "--directory", "--output"))
        if "--dry-run" in opts:
            return Action("other", program)
        return Action("edit", program, *where.split(words[:1]))
    if _is_test(program, args):
        name = program if program in _TESTERS else f"{program} {next(a for a in args if not a.startswith('-'))}"
        return Action("test", name, *where.split(_test_paths(args)))
    if program.startswith("python") or program in ("pypy3", "node", "perl", "ruby"):
        return _python_like(cmd, program, args, where)
    if program in ("bash", "sh", "zsh"):
        return Action("run", program, *where.split([a for a in args if not a.startswith("-")][:1]))
    if program in _RUNNERS:
        return Action("run", program, *where.split([w for w in args if _pathish(w)]))
    if cmd.words[0].startswith(("./", "/", "../")) and program not in _OTHER:
        return Action("run", program, *where.split(cmd.words[:1]))
    if program in _FILTERS:
        return Action("filter" if cmd.piped_in else "other", program)
    return Action("other", program)


def classify_call(command: str, cwd: str | None = None, repo_root: str = REPO_ROOT
                  ) -> tuple[list[tuple[SimpleCommand, Action]], str]:
    """The simple commands of one Bash call and their actions, and the folder at the end of the call. A cd in
    the call changes the folder for the commands after it (a subshell or a failed cd is not seen)."""
    root = repo_root.rstrip("/") or "/"
    cwd = cwd or root
    pairs: list[tuple[SimpleCommand, Action]] = []
    for cmd in split_commands(command):
        pairs.append((cmd, classify(cmd, cwd, root)))
        if cmd.program in ("cd", "pushd") and cmd.kind != "unparsed" and not cmd.nested:
            target = next((a for a in cmd.args if not a.startswith("-")), None)
            if target is None or target.startswith("~"):
                cwd = "/home"  # the home folder: outside the repo
            elif target != "-" and "$" not in target and "`" not in target:
                cwd = _Where(cwd, root).resolve(target)
    # `cat -n a.py | sed -n 10,40p` and `cat a.py | head -50` show the range of the filter.
    for k in range(len(pairs) - 1):
        (cmd, view), (_, part) = pairs[k], pairs[k + 1]
        if view.kind == "view" and view.whole_file and cmd.piped_out and part.kind == "filter" \
                and (part.lines is not None or part.first_line is not None):
            pairs[k] = (cmd, replace(view, whole_file=False, first_line=part.first_line, last_line=part.last_line,
                                     lines=part.lines, shows_output=part.shows_output))
    return pairs, cwd


# ---- reading a stream

def parse_stream(path: Path) -> dict:
    """The events of Claude Code's stream-json output: the init event, the result event, all events, and the
    count of lines that are not JSON (for example a line cut off by a kill)."""
    events, bad = [], 0
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(event, dict):
            events.append(event)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    return {"events": events, "init": init, "result": result, "bad_lines": bad}


class TurnCounter:
    """Counts the turns of the main agent and of its subagents in the stream.

    One turn is one model answer: one `assistant` event with a new message.id. Claude Code writes one event
    for each content block, so several events can share one id. Events of a subagent (Task tool) have a
    parent_tool_use_id that is not null; they are counted apart and are not turns of the main agent.
    The result event's num_turns is Claude Code's own count. We expect it to be close to ours. It is not
    documented whether it counts the last answer or subagent answers, so the record keeps both.
    """

    def __init__(self) -> None:
        self.main: set[str] = set()
        self.sub: set[str] = set()
        self._anonymous = 0

    def feed(self, event: dict) -> bool:
        """Count one event. True when it starts a new turn of the main agent."""
        if event.get("type") != "assistant":
            return False
        message_id = (event.get("message") or {}).get("id")
        if not message_id:
            self._anonymous += 1
            message_id = f"no-id-{self._anonymous}"
        ids = self.sub if event.get("parent_tool_use_id") else self.main
        if message_id in ids:
            return False
        ids.add(message_id)
        return ids is self.main

    @property
    def turns(self) -> int:
        return len(self.main)


def result_text(block: dict) -> str:
    """The text of a tool_result block: a string, or a list of text blocks."""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
    return ""


def _results(events: list[dict]) -> dict[str, tuple[str, bool]]:
    """The text of each tool result, and whether Claude Code marked it as its own error (<tool_use_error>)."""
    found = {}
    for event in events:
        if event.get("type") != "user":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                text = result_text(block)
                found[block["tool_use_id"]] = (text, text.lstrip().startswith("<tool_use_error>"))
    return found


_REFUSED = re.compile(r"<tool_use_error>\s*(Blocked|Permission|.{0,200}(denied|haven't granted|hook))", re.S)


def blocked(tool: str, result: str | None, tool_error: bool) -> bool:
    """True when Claude Code did not run the call. A Bash command that runs and fails gets "Exit code N"; a
    <tool_use_error> means that Claude Code stopped it before it ran (for example "Blocked: sleep 100 followed
    by ..."). For other tools only a refusal counts: an Edit whose old text is not found also gets a
    <tool_use_error>, and it still counts as an edit."""
    if not tool_error or result is None:
        return False
    return tool == "Bash" or bool(_REFUSED.match(result.lstrip()))


# ---- the counts of a run

def path_pattern(path: str, repo_root: str = REPO_ROOT) -> re.Pattern:
    """A pattern that finds a repo path in text as a whole path: with or without the repo root, ./, or the a/
    and b/ of a git diff before it, and not as a part of a longer path."""
    root = re.escape((repo_root.rstrip("/") or "") + "/")
    return re.compile(rf"(?<![\w./-])(?:{root}|\./|[ab]/)?{re.escape(path)}(?![\w/-]|\.\w)")


def _short_pattern(text: str) -> re.Pattern:
    """A pattern that finds a relative path or a file name in text as a whole word."""
    return re.compile(rf"(?<![\w./-])(?:\./)?{re.escape(text)}(?![\w/-]|\.\w)")


def _short_patterns(gold: str, actions: list[Action], folders: set[str]) -> list[re.Pattern]:
    """Patterns for the shorter forms of a gold path that a Bash call can print: the path relative to the shell's
    folder (grep -rn after a cd), and the bare file name in a listing of its folder (ls, or a recursive ls or
    tree of a folder above it). `folders` are the shell's folders at the start and the end of the call."""
    found = []
    for folder in folders:
        if folder not in (".", "") and not folder.startswith("/") and gold.startswith(folder + "/"):
            found.append(_short_pattern(gold[len(folder) + 1:]))
    parent = posixpath.dirname(gold) or "."
    for a in actions:
        if a.kind != "search_files" or a.program not in ("ls", "tree"):
            continue
        listed = a.paths or (() if a.outside else tuple(folders))
        if any(f == parent or (a.recursive and (f == "." or gold.startswith(f.rstrip("/") + "/"))) for f in listed):
            found.append(_short_pattern(posixpath.basename(gold)))
            break
    return found


def _norm_gold(path: str, root: str) -> str:
    path = path.removeprefix(root + "/")
    return posixpath.normpath(path) if path else path


def _matches(target: str, gold: str) -> bool:
    if target == gold:
        return True
    return any(ch in target for ch in "*?[") and fnmatch.fnmatchcase(gold, target)


def _any_match(targets, gold: str) -> bool:
    return any(_matches(t, gold) for t in targets)


def _edit_targets(action: Action) -> tuple[str, ...]:
    """The repo files that an action writes: the targets of an edit, and the files of a redirection."""
    return (action.paths if action.kind in ("edit", "edit_script") else ()) + action.writes


def _numbered_lines(text: str) -> int:
    """The lines of a Read result: it numbers each line of the file."""
    numbered = len(re.findall(r"^\s*\d+[\t→]", text, re.M))
    return numbered or len(text.splitlines())


def _tool_actions(name: str, args: dict, where: _Where) -> list[Action]:
    """The actions of a tool call that is not Bash."""
    path_arg = args.get("file_path") or args.get("notebook_path") or args.get("path")
    paths, outside = where.split([str(path_arg)]) if path_arg else ((), ())
    if name == "Read":
        limit = args.get("limit")
        offset = args.get("offset")
        return [_place(Action("view", "Read", paths, outside, first_line=offset if isinstance(offset, int) else None,
                              lines=limit if isinstance(limit, int) else None, whole_file=not (limit or offset)),
                       where)]
    if name in EDIT_TOOLS:
        return [_place(Action("edit", name, paths, outside), where)]
    if name == "Grep":  # older Claude Code versions
        return [Action("search_content", "Grep", paths, outside, pattern=args.get("pattern"), recursive=True)]
    if name == "Glob":
        return [Action("search_files", "Glob", paths, outside, pattern=args.get("pattern"), recursive=True)]
    if name.startswith(MCP_PREFIX):
        return [Action("mcp", name)]
    return []


class _Tally:
    """The counts of one agent (the main agent, or all subagents together)."""

    def __init__(self) -> None:
        self.actions: Counter = Counter({k: 0 for k in KINDS})
        self.mcp_tools: Counter = Counter()
        self.programs: Counter = Counter()
        self.files_viewed: list[str] = []
        self.views = Counter()
        self.edits = Counter()
        self.files_edited: list[str] = []
        self.files_edited_guess: list[str] = []
        self.bash_calls = 0
        self.bash_commands = 0
        self.blocked_calls = 0

    def add(self, actions: list[Action], tool: str, result: str | None) -> bool:
        """Count the actions of one tool call. True when it edits a repo file (or files it cannot name)."""
        edits_repo = False
        whole = [a for a in actions if a.kind == "view" and a.whole_file and a.shows_output and a.lines is None]
        shown = [a for a in actions if a.shows_output and a.kind not in ("other", "unparsed")]
        for a in actions:
            self.actions[a.kind] += 1
            if a.kind == "mcp":
                self.mcp_tools[a.program] += 1
            if a.kind in ("search_content", "search_files"):
                self.programs[a.program] += 1
            if a.kind == "view":
                self.views["count"] += 1
                self.views["whole_file_views"] += a.whole_file
                _extend(self.files_viewed, a.paths)
                # The lines of a view: Read counts the lines it returned; a range counts when its output reaches
                # the result; a whole file counts the lines of the result when it is the only output of the call.
                if tool == "Read" and result is not None:
                    numbered = _numbered_lines(result)
                    self.views["lines_viewed"] += min(a.lines, numbered) if a.lines else numbered
                elif a.lines is not None and (a.shows_output or tool == "Read"):
                    self.views["lines_viewed"] += a.lines
                elif a.whole_file and len(whole) == 1 and len(shown) == 1 and result is not None:
                    self.views["lines_viewed"] += len(result.splitlines())
                else:
                    self.views["lines_unknown"] += 1
            if a.kind == "revert":
                self.edits["reverts"] += 1
            if a.kind == "write_outside":
                self.edits["outside"] += 1
            certain = a.paths if a.kind == "edit" else ()
            guessed = a.paths if a.kind == "edit_script" else ()
            written = certain + guessed + a.writes
            # git apply, patch, or a script that names no file: the files are not known. It counts as an edit of
            # the repo, because the shell starts in the repo.
            unknown = a.kind in ("edit", "edit_script") and not a.paths and not a.outside
            if a.kind in ("edit", "edit_script") or a.writes:
                if written or unknown:
                    edits_repo = True
                    by = "tool" if tool in EDIT_TOOLS else "script" if a.kind == "edit_script" else "shell"
                    self.edits[by] += 1
                elif a.kind in ("edit", "edit_script"):
                    self.edits["outside"] += 1
            _extend(self.files_edited, certain + a.writes)
            _extend(self.files_edited_guess, [p for p in guessed if p not in self.files_edited])
        return edits_repo

    def kinds(self) -> dict:
        return dict(self.actions)


def _extend(target: list[str], paths) -> None:
    for path in paths:
        if path not in target and path != ".":
            target.append(path)


def _first(current: int | None, turn: int) -> int:
    return turn if current is None else current


def count_steps(events: list[dict], gold_files: list[str], repo_root: str = REPO_ROOT) -> dict:
    """What the agent did: turns, tool calls, searches, views, edits, tests, and when it met the gold files.

    The counts are those of the main agent. A subagent's turns, tool calls and actions are counted apart; a
    subagent's event belongs to the main turn of its Task call. Turn numbers start at 1 and are null when the
    thing did not happen. For each gold file:

      surfaced        first turn in which the file reaches the agent: a tool result shows its path (a search
                      hit, a listing, a trace), or the agent views the file or greps inside it by name
      opened          first turn with a view of the file (Read, cat, sed -n, head, ...)
      edited          first turn with an edit of the file (an edit that failed counts; a guess of an
                      edit_script counts; a revert does not)
      named_by_agent  first turn in which the agent wrote the path in a tool call

    A call that Claude Code did not run (see `blocked`) adds nothing but tool_calls, bash_calls, bash_commands,
    blocked_calls and named_by_agent; its result surfaces nothing. `commands` holds each Bash call (of the main
    agent and of subagents) with the kind, program and paths of its simple commands, and "blocked" when it did
    not run, so that anyone can count again. gold_file_read and first_gold_read_turn are the names
    of version 1. They are kept as copies of gold_opened and first_gold_opened_turn, so that e2e_score and
    older readers still work.
    """
    root = repo_root.rstrip("/") or "/"
    gold_list = [_norm_gold(g, root) for g in gold_files]
    patterns = {g: path_pattern(g, root) for g in gold_list}
    gold = {g: {"surfaced": None, "opened": None, "edited": None, "named_by_agent": None} for g in gold_list}
    results = _results(events)
    counter = TurnCounter()
    main, sub = _Tally(), _Tally()
    tools, sub_tools = Counter(), Counter()
    call_turn: dict[str, int] = {}
    blocked_ids: set[str] = set()
    short: dict[str, dict[str, list[re.Pattern]]] = {}  # call id -> gold file -> patterns of shorter forms
    marks = {"first_edit_turn": None, "first_test_turn": None, "first_mcp_turn": None, "first_codemem_turn": None}
    commands = []
    cwd = root
    for event in events:
        counter.feed(event)
        turn = counter.turns
        is_sub = bool(event.get("parent_tool_use_id"))
        if event.get("type") == "user" and not is_sub:
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and \
                        block.get("tool_use_id") in call_turn and block.get("tool_use_id") not in blocked_ids:
                    text = result_text(block)
                    extra = short.get(block["tool_use_id"], {})
                    for g, pattern in patterns.items():
                        if gold[g]["surfaced"] is None and (pattern.search(text)
                                                            or any(p.search(text) for p in extra.get(g, ()))):
                            gold[g]["surfaced"] = call_turn[block["tool_use_id"]]
            continue
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name, args, call_id = block.get("name", "?"), block.get("input") or {}, block.get("id")
            if not isinstance(args, dict):
                args = {}
            tally = sub if is_sub else main
            (sub_tools if is_sub else tools)[name] += 1
            if call_id and not is_sub:
                call_turn[call_id] = turn
            result, tool_error = results.get(call_id, (None, False)) if call_id else (None, False)
            not_run = blocked(name, result, tool_error)
            start = cwd if (CD_PERSISTS and not is_sub) else root
            if name == "Bash":
                text = str(args.get("command") or "")
                pairs, end = classify_call(text, start, root)
                actions = [a for _, a in pairs]
                tally.bash_calls += 1
                tally.bash_commands += len(pairs)
                entry = {"turn": turn, "command": text[:MAX_COMMAND_CHARS], "cut": len(text) > MAX_COMMAND_CHARS,
                         "cwd": _Where(start, root).norm(start)[0],
                         "simple": [[a.kind, a.program, list(a.paths + a.outside)] for a in actions]}
                if is_sub:
                    entry["subagent"] = True
                if not_run:
                    entry["blocked"] = True
                commands.append(entry)
                if not is_sub and not not_run:
                    inside = end == root or end.startswith(root + "/")
                    cwd = end if inside else root
                    if call_id:
                        folders = {_Where(start, root).norm(start)[0], _Where(end, root).norm(end)[0]}
                        short[call_id] = {g: _short_patterns(g, actions, folders) for g in gold_list}
            else:
                text = json.dumps(args, ensure_ascii=False)
                actions = _tool_actions(name, args, _Where(start, root))
            if not_run:  # the call is in tool_calls (and in commands), but nothing in it happened
                tally.blocked_calls += 1
                actions = []
                if call_id:
                    blocked_ids.add(call_id)
            edits_repo = tally.add(actions, name, result)
            if is_sub:
                continue
            if edits_repo:
                marks["first_edit_turn"] = _first(marks["first_edit_turn"], turn)
            if any(a.kind == "test" for a in actions):
                marks["first_test_turn"] = _first(marks["first_test_turn"], turn)
            if name.startswith(MCP_PREFIX):
                marks["first_mcp_turn"] = _first(marks["first_mcp_turn"], turn)
            if name.startswith(CODEMEM_PREFIX):
                marks["first_codemem_turn"] = _first(marks["first_codemem_turn"], turn)
            touched = [p for a in actions for p in a.paths + a.writes]
            viewed = [p for a in actions if a.kind == "view" for p in a.paths]
            searched = [p for a in actions if a.kind == "search_content" for p in a.paths]
            edited = [p for a in actions for p in _edit_targets(a)]
            for g, pattern in patterns.items():
                marks_of = gold[g]
                if marks_of["named_by_agent"] is None and (pattern.search(text) or _any_match(touched, g)):
                    marks_of["named_by_agent"] = turn
                # The file's content reaches the agent without its path: a view, or a grep in the one file.
                if marks_of["surfaced"] is None and (_any_match(viewed, g) or g in searched):
                    marks_of["surfaced"] = turn
                if marks_of["opened"] is None and _any_match(viewed, g):
                    marks_of["opened"] = turn
                if marks_of["edited"] is None and _any_match(edited, g):
                    marks_of["edited"] = turn

    def first(key: str) -> int | None:
        turns = [v[key] for v in gold.values() if v[key] is not None]
        return min(turns) if turns else None

    opened = sum(v["opened"] is not None for v in gold.values())
    first_edit = marks["first_edit_turn"]
    steps = {
        "steps_version": STEPS_VERSION,
        "turns": counter.turns,
        "subagent_turns": len(counter.sub),
        "tool_calls": dict(tools),
        "subagent_tool_calls": dict(sub_tools),
        "bash_calls": main.bash_calls,
        "bash_commands": main.bash_commands,
        "blocked_calls": main.blocked_calls,
        "actions": main.kinds(),
        "mcp_tools": dict(main.mcp_tools),
        "codemem_calls": sum(n for t, n in main.mcp_tools.items() if t.startswith(CODEMEM_PREFIX)),
        "searches": {"content": main.actions["search_content"], "files": main.actions["search_files"],
                     "programs": dict(main.programs)},
        "views": {"count": main.views["count"], "files_viewed": main.files_viewed,
                  "lines_viewed": main.views["lines_viewed"], "whole_file_views": main.views["whole_file_views"],
                  "lines_unknown": main.views["lines_unknown"]},
        "edits": {"tool": main.edits["tool"], "shell": main.edits["shell"], "script": main.edits["script"],
                  "outside": main.edits["outside"], "reverts": main.edits["reverts"], "files_edited": main.files_edited,
                  "files_edited_guess": main.files_edited_guess},
        "tests_run": main.actions["test"],
        **marks,
        "turns_before_first_edit": first_edit - 1 if first_edit else None,
        "subagent_bash_calls": sub.bash_calls,
        "subagent_actions": sub.kinds(),
        "subagent_files_viewed": sub.files_viewed,
        "gold": gold,
        "gold_files": gold_list,
        "gold_surfaced": first("surfaced") is not None,
        "first_gold_surfaced_turn": first("surfaced"),
        "gold_opened": opened > 0,
        "first_gold_opened_turn": first("opened"),
        "gold_opened_share": opened / len(gold) if gold else None,
        "gold_edited": first("edited") is not None,
        "first_gold_edited_turn": first("edited"),
        "gold_file_read": opened > 0,
        "first_gold_read_turn": first("opened"),
        "commands": commands,
    }
    return steps
