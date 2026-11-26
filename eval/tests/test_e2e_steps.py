"""The shell command reader, the classifier and the step counts of e2e_steps.

The two fixtures e2e_stream_pandas_70742.jsonl and e2e_stream_pandas_66227.jsonl are real streams of Claude Code
(claude-haiku-5-5, setup grep) on two pandas tasks. To keep them small, each was made from the full stream like
this: drop the thinking blocks of assistant events (an event with no block left is kept, for its message id),
drop the tool_use_result and tool_result_meta fields of user events (copies of the tool result), and cut the
text of each tool_result block to its first 2,000 characters. Every tool_use is kept in full. count_steps gives
the same result on each fixture and on its full stream. The command strings below are copied from them.
"""

import json
import random

import pytest

from cmeval import e2e_run, e2e_steps
from cmeval.cli import main
from cmeval.e2e_score import format_score, score
from cmeval.e2e_steps import Action, Redirect, classify, classify_call, count_steps, split_commands
from cmeval.files import write_json

from conftest import FIXTURES

FIXTURE_70742 = FIXTURES / "e2e_stream_pandas_70742.jsonl"
FIXTURE_66227 = FIXTURES / "e2e_stream_pandas_66227.jsonl"
GOLD_70742 = ["pandas/core/indexing.py"]
GOLD_66227 = ["pandas/core/arrays/timedeltas.py"]


def _summary(command: str, cwd: str | None = None) -> list[tuple]:
    """(kind, program, paths) of each simple command, with the paths outside the repo last."""
    pairs, _ = classify_call(command, cwd)
    return [(a.kind, a.program, list(a.paths + a.outside)) for _, a in pairs]


def _one(command: str, cwd: str | None = None) -> Action:
    pairs, _ = classify_call(command, cwd)
    assert len(pairs) == 1, pairs
    return pairs[0][1]


def _bash_calls(path) -> list[str]:
    calls = []
    for line in path.read_text().splitlines():
        event = json.loads(line)
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                calls.append(block["input"]["command"])
    return calls


# ---- split_commands

def test_split_at_operators_but_not_inside_quotes():
    cmds = split_commands("a 1; b 'x;y|z' && c \"p | q\" || d | e & f\ng")
    assert [c.words for c in cmds] == [("a", "1"), ("b", "x;y|z"), ("c", "p | q"), ("d",), ("e",), ("f",), ("g",)]
    assert [c.piped_in for c in cmds] == [False, False, False, False, True, False, False]
    assert [c.piped_out for c in cmds] == [False, False, False, True, False, False, False]


def test_split_keeps_redirections_apart():
    cmd, = split_commands("python run.py > /tmp/out.txt 2>&1")
    assert cmd.words == ("python", "run.py")
    assert cmd.redirects == (Redirect(">", "/tmp/out.txt"), Redirect(">&", "1", "2"))
    assert cmd.redirects[0].writes_file and not cmd.redirects[1].writes_file
    cmd, = split_commands("echo hi >>notes.md")
    assert cmd.words == ("echo", "hi") and cmd.redirects == (Redirect(">>", "notes.md"),)
    cmd, = split_commands("make &> build.log")
    assert cmd.redirects == (Redirect(">", "build.log", "&"),) and cmd.redirects[0].hides_output
    cmd, = split_commands("sort < in.txt")
    assert cmd.words == ("sort",) and cmd.redirects == (Redirect("<", "in.txt"),)
    # A quoted > is a word, not a redirection.
    cmd, = split_commands("grep '>' a.py")
    assert cmd.words == ("grep", ">", "a.py") and cmd.redirects == ()
    cmd, = split_commands("cat x 2>/dev/null")
    assert not cmd.redirects[0].writes_file


@pytest.mark.parametrize("operator", ["<<EOF", "<<'EOF'", '<<"EOF"', "<<-EOF", "<< EOF"])
def test_heredoc_body_is_not_parsed(operator):
    text = f"cat > /tmp/x.py {operator}\nimport os; rm -rf /\nx = 1 | 2\n\tEOF\nEOF\necho done"
    if operator == "<<-EOF":
        text = text.replace("\tEOF\nEOF", "\tEOF")  # <<- strips leading tabs: the tab line closes the body
    cmds = split_commands(text)
    assert [c.program for c in cmds] == ["cat", "echo"]
    assert cmds[0].heredoc.startswith("import os; rm -rf /\nx = 1 | 2")
    assert cmds[0].redirects[0] == Redirect(">", "/tmp/x.py")


def test_heredoc_owner_is_the_command_that_has_the_operator():
    cmds = split_commands("python - <<'PY' && echo ok\nprint(1)\nPY\nls")
    assert [(c.program, c.heredoc) for c in cmds] == [("python", "print(1)"), ("echo", None), ("ls", None)]
    cmd, = split_commands("cat <<EOF")  # no body and no closing line
    assert cmd.heredoc == ""


def test_substitutions_are_kept_and_read():
    cmds = split_commands('vim "$(grep -l foo src/a.py; echo x)" `find . -name b.py`')
    assert cmds[0].words == ("vim", "$(grep -l foo src/a.py; echo x)", "`find . -name b.py`")
    assert [(c.program, c.nested) for c in cmds] == [("vim", False), ("grep", True), ("echo", True), ("find", True)]
    # Arithmetic and parameter expansion hold no commands, and their ; | do not split.
    cmds = split_commands("echo $((1 + 2)) ${A:-x;y} | wc -l")
    assert [c.program for c in cmds] == ["echo", "wc"]
    cmds = split_commands("diff <(sort a.txt) <(sort b.txt)")
    assert [c.program for c in cmds] == ["diff", "sort", "sort"]


def test_wrappers_and_assignments_are_removed():
    assert split_commands("timeout 1500 python -m pytest x")[0].words == ("python", "-m", "pytest", "x")
    assert split_commands("timeout -k 5 60s pytest")[0].words == ("pytest",)
    assert split_commands("LC_ALL=C A=1 /usr/bin/find . -name '*.py'")[0].program == "find"
    assert split_commands("env -u X A=1 nice -n 5 sudo -u agent stdbuf -oL grep x a")[0].words == ("grep", "x", "a")
    assert split_commands("time command ls -la")[0].words == ("ls", "-la")
    cmd = split_commands("find . -name '*.py' | xargs -I{} grep -n foo {}")[1]
    assert cmd.words == ("grep", "-n", "foo", "{}") and cmd.via_xargs and cmd.piped_in


def test_groups_comments_and_continuations():
    cmds = split_commands("(ruff check a.py 2>&1 | tail -3; ruff format a.py); git status --short")
    assert [c.program for c in cmds] == ["ruff", "tail", "ruff", "git"]
    assert split_commands("a | (b; c)")[1].piped_in
    assert [c.words for c in split_commands("ls # list; rm x\necho 'a # b'")] == [("ls",), ("echo", "a # b")]
    assert split_commands("grep -rn \\\n  foo .")[0].words == ("grep", "-rn", "foo", ".")
    assert [c.program for c in split_commands("if [ -f a ]; then cat a; fi")] == ["[", "cat"]
    assert [c.program for c in split_commands("{ cat a; }")] == ["cat"]


def test_bash_c_and_find_exec_are_read():
    cmds = split_commands("bash -lc 'cd pandas && grep -rn x .'")
    assert [(c.program, c.nested) for c in cmds] == [("cd", True), ("grep", True)]
    cmds = split_commands("find . -name '*.py' -exec grep -l foo {} \\;")
    assert [c.program for c in cmds] == ["find", "grep"] and cmds[1].nested
    assert _summary("find pandas -name '*.py' -exec grep -l 'def xs' {} +") == [
        ("search_files", "find", ["pandas"]), ("search_content", "grep", [])]


def test_unparsed():
    cmds = split_commands("ls a; echo 'unclosed")
    assert [(c.program, c.kind) for c in cmds] == [("ls", "simple"), ("echo", "unparsed")]
    assert split_commands("") == [] and split_commands("  \n ") == []
    assert classify(split_commands("cat $(echo")[0]).kind == "unparsed"


def test_split_never_raises():
    rng = random.Random(7)
    alphabet = "ab /.-'\"`$(){}[];&|<>\\#\n\t=*!~0123456789EOF"
    texts = ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80))) for _ in range(250)]
    texts += [bytes(rng.randrange(256) for _ in range(rng.randint(0, 60))).decode("latin-1") for _ in range(50)]
    texts += _bash_calls(FIXTURE_70742) + _bash_calls(FIXTURE_66227)
    for text in texts:
        for cmd in split_commands(text):
            assert isinstance(classify(cmd), Action)


# ---- classify

@pytest.mark.parametrize("command, expected", [
    # Content searches, and grep that filters a pipe.
    ('grep -rn "def checked_add_with_arr" -A3 pandas/core/algorithms.py pandas/core/missing.py pandas/core/ops/*.py',
     ("search_content", "grep", ["pandas/core/algorithms.py", "pandas/core/missing.py", "pandas/core/ops/*.py"])),
    ('grep -rn "overflow in timedelta operation\\|Overflow in int64 addition" pandas/_libs pandas/core',
     ("search_content", "grep", ["pandas/_libs", "pandas/core"])),
    ("rg -n 'def xs' pandas", ("search_content", "rg", ["pandas"])),
    ("git grep -n fast_xs -- pandas/core", ("search_content", "git grep", ["pandas/core"])),
    ("ag foo", ("search_content", "ag", [])),
    ("grep -e foo -e bar a.py b.py", ("search_content", "grep", ["a.py", "b.py"])),
    # File searches.
    ("find pandas/core -name '*.py' -type f", ("search_files", "find", ["pandas/core"])),
    ("ls -la pandas/core/arrays", ("search_files", "ls", ["pandas/core/arrays"])),
    ("tree -L 2 pandas", ("search_files", "tree", ["pandas"])),
    ("git ls-files pandas/core", ("search_files", "git ls-files", ["pandas/core"])),
    ("rg --files pandas/io", ("search_files", "rg --files", ["pandas/io"])),
    ("fd indexing pandas", ("search_files", "fd", ["pandas"])),
    # Views.
    ("sed -n 1199,1240p pandas/core/indexing.py", ("view", "sed -n", ["pandas/core/indexing.py"])),
    ("sed -n 105,130p /testbed/pandas/tests/series/test_reductions.py",
     ("view", "sed -n", ["pandas/tests/series/test_reductions.py"])),
    ("cat ./setup.py", ("view", "cat", ["setup.py"])),
    ("tail -3 pandas/tests/indexing/test_indexing.py", ("view", "tail", ["pandas/tests/indexing/test_indexing.py"])),
    ("nl -ba pandas/core/frame.py", ("view", "nl", ["pandas/core/frame.py"])),
    ("wc -l pandas/core/frame.py", ("view", "wc", ["pandas/core/frame.py"])),
    ("awk 'NR>=10 && NR<=20' a.py", ("view", "awk", ["a.py"])),
    ("git show HEAD:pandas/core/indexing.py", ("view", "git show", ["pandas/core/indexing.py"])),
    ("git blame -L 10,20 pandas/core/indexing.py", ("view", "git blame", ["pandas/core/indexing.py"])),
    ("git diff pandas/core/indexing.py", ("view_git", "git diff", ["pandas/core/indexing.py"])),
    ("git log -p -3", ("view_git", "git log", [])),
    ("git show HEAD", ("view_git", "git show", [])),
    # Edits.
    ("sed -i 's/a/b/' pandas/core/indexing.py", ("edit", "sed -i", ["pandas/core/indexing.py"])),
    ("perl -pi -e 's/a/b/' x.py", ("edit", "perl -i", ["x.py"])),
    ("echo x >> notes.md", ("edit", "echo", ["notes.md"])),
    ("tee pandas/a.py", ("edit", "tee", ["pandas/a.py"])),
    ("git checkout -- pandas/core/indexing.py", ("revert", "git checkout", ["pandas/core/indexing.py"])),
    ("git restore pandas/a.py", ("revert", "git restore", ["pandas/a.py"])),
    ("git apply /tmp/fix.diff", ("edit", "git apply", [])),
    ("patch -p1 < /tmp/fix.diff", ("edit", "patch", [])),
    ("cp pandas/a.py /tmp/a.bak", ("write_outside", "cp", ["/tmp/a.bak"])),
    ("cp /tmp/a.py pandas/core/", ("edit", "cp", ["pandas/core/a.py"])),
    ("mv a.py b.py", ("edit", "mv", ["a.py", "b.py"])),
    ("rm -f /tmp/repro.py", ("write_outside", "rm", ["/tmp/repro.py"])),
    ("mkdir -p pandas/new", ("edit", "mkdir", ["pandas/new"])),
    ("python -c \"open('pandas/a.py', 'w').write('x')\"", ("edit_script", "python", ["pandas/a.py"])),
    ("node -e \"require('fs').writeFileSync('src/a.js', s)\"", ("edit_script", "node", ["src/a.js"])),
    # Tests, runs and git.
    ("timeout 1500 python -m pytest pandas/tests/indexing -q -x -p no:cacheprovider",
     ("test", "python -m pytest", ["pandas/tests/indexing"])),
    ("pytest pandas/tests/test_a.py::test_b -k x", ("test", "pytest", ["pandas/tests/test_a.py"])),
    ("npx playwright test tests/a.spec.ts", ("test", "npx playwright", ["tests/a.spec.ts"])),
    ("npm run test:unit", ("test", "npm run", [])),
    ("make test", ("test", "make test", [])),
    ("cargo test", ("test", "cargo test", [])),
    ("go test ./...", ("test", "go test", ["..."])),
    ("timeout 600 python -I /tmp/repro.py", ("run", "python", ["/tmp/repro.py"])),
    ("python -c 'import pandas; print(pandas.__version__)'", ("run", "python", [])),
    ("python -m pip install -e .", ("run", "python -m pip", [])),
    ("npm install", ("run", "npm", [])),
    ("./run.sh", ("run", "run.sh", ["run.sh"])),
    ("ruff format --check pandas/core/arrays/timedeltas.py", ("run", "ruff", ["pandas/core/arrays/timedeltas.py"])),
    ("git status --short", ("git", "git status", [])),
    ("git diff --stat", ("git", "git diff", [])),
    ("git log --oneline", ("git", "git log", [])),
    ("git stash", ("git", "git stash", [])),
    ("echo ----", ("other", "echo", [])),
    ("sleep 5", ("other", "sleep", [])),
])
def test_classify(command, expected):
    assert _summary(command) == [expected]


def test_filters_read_a_pipe():
    assert _summary("git log --oneline | head -3")[1] == ("filter", "head", [])
    assert _summary("pytest 2>&1 | tail -15")[1] == ("filter", "tail", [])
    assert _summary('grep -rn x pandas | grep -i "sum\\|mul" | head -20')[1:] == [("filter", "grep", []),
                                                                             ("filter", "head", [])]
    assert _summary('grep -n "def _getitem_tuple" -A30 pandas/core/indexing.py | sed -n 1,5p')[1] == \
        ("filter", "sed -n", [])
    # A grep fed file names by xargs searches files; a recursive grep in a pipe searches the folder.
    assert _summary("git ls-files | xargs grep -n foo") == [("search_files", "git ls-files", []),
                                                            ("search_content", "grep", [])]
    assert _summary("echo | grep -r foo")[1][0] == "search_content"


def test_line_ranges():
    a = _one("sed -n 1199,1240p pandas/core/indexing.py")
    assert (a.first_line, a.last_line, a.lines, a.whole_file) == (1199, 1240, 42, False)
    a = _one("sed -n '10,12p;20p' a.py")
    assert (a.first_line, a.last_line, a.lines) == (10, 20, 4)
    a = _one("sed -n '/def x/,/def y/p' a.py")
    assert a.kind == "view" and a.lines is None and not a.whole_file
    assert _one("sed -n 100,\\$p a.py").first_line == 100 and _one("sed -n 100,\\$p a.py").lines is None
    assert _one("sed 's/a/b/' a.py").whole_file
    assert _one("head -n 50 a.py").lines == 50 and _one("head -50 a.py").lines == 50
    assert _one("head a.py").lines == 10 and _one("tail -n 30 a.py").lines == 30
    a = _one("tail -n +100 a.py")
    assert (a.first_line, a.lines) == (100, None)
    assert _one("cat a.py b.py").whole_file and _one("wc -l a.py").lines == 0
    assert _one("bat -r 5:9 a.py").lines == 5
    # A whole file that goes into head or sed -n shows the filter's range.
    pairs, _ = classify_call("cat -n a.py | sed -n 10,40p")
    a = pairs[0][1]
    assert (a.kind, a.first_line, a.lines, a.whole_file, a.shows_output) == ("view", 10, 31, False, True)
    pairs, _ = classify_call("cat a.py | head -50 | grep x")
    assert (pairs[0][1].lines, pairs[0][1].shows_output) == (50, False)


def test_paths_are_relative_to_the_repo():
    assert _one("cat /testbed/pandas/a.py").paths == ("pandas/a.py",)
    assert _one("cat ./pandas/../setup.py").paths == ("setup.py",)
    a = _one("cat /tmp/repro.py ../x.py")
    assert a.paths == () and a.outside == ("/tmp/repro.py", "/x.py")
    assert _one("cat a.py", cwd="/testbed/pandas/core").paths == ("pandas/core/a.py",)
    assert _one("ls", cwd="/testbed").paths == ()
    assert _one("ls .").paths == (".",)
    assert _one("cat $FILE").paths == ()
    assert _summary("cd pandas/core && sed -n 1,5p indexing.py && cd .. && cat io/x.py") == [
        ("other", "cd", []), ("view", "sed -n", ["pandas/core/indexing.py"]),
        ("other", "cd", []), ("view", "cat", ["pandas/io/x.py"])]
    _, cwd = classify_call("cd pandas && ls")
    assert cwd == "/testbed/pandas"
    assert classify_call("cd /testbed && ls", cwd="/testbed/pandas")[1] == "/testbed"
    assert _summary("git -C pandas show HEAD:./core/a.py") == [("view", "git show", ["pandas/core/a.py"])]


def test_redirections_make_edits():
    a = _one("cat > /tmp/repro.py <<'EOF'\nprint(1)\nEOF")
    assert (a.kind, a.paths, a.outside) == ("write_outside", (), ("/tmp/repro.py",))
    a = _one("cat >> pandas/tests/test_a.py <<'EOF'\ndef test(): pass\nEOF")
    assert (a.kind, a.paths) == ("edit", ("pandas/tests/test_a.py",))
    # A test or a search keeps its kind; the written file is in `writes`.
    a = _one("python -m pytest x > out.log 2>&1")
    assert (a.kind, a.writes, a.shows_output) == ("test", ("out.log",), False)
    a = _one("grep -rn foo pandas > /tmp/hits.txt")
    assert (a.kind, a.writes_outside) == ("search_content", ("/tmp/hits.txt",))
    assert _one("cat a.py > /dev/null").kind == "view"


def test_edit_script_guesses_targets():
    command = ('python - <<\'EOF\'\np="pandas/tests/indexing/test_indexing.py"\ns=open(p).read()\n'
               's=s.replace("a", "b")\nopen(p,"w").write(s)\nEOF')
    a = _one(command)
    assert (a.kind, a.paths, a.guess) == ("edit_script", ("pandas/tests/indexing/test_indexing.py",), True)
    reader = "python - <<'EOF'\nprint(open('pandas/a.py').read())\nEOF"
    assert _one(reader).kind == "run"
    assert _one("python -c \"open('/tmp/x.txt', 'a').write('1')\"").outside == ("/tmp/x.txt",)


# All Bash calls of the two transcripts, in order, with (kind, program, paths) of each simple command.
TRANSCRIPT = [
    # pandas-dev__pandas-70742
    ('git log --oneline | head -3 && git status --short | head && grep -n "def '
     '_getitem_lowerdim\\|def _multi_take\\|def _handle_lowerdim_multi_index_axis0\\|def '
     '_getitem_tuple\\b" pandas/core/indexing.py',
     [('git', 'git log', []),
      ('filter', 'head', []),
      ('git', 'git status', []),
      ('filter', 'head', []),
      ('search_content', 'grep', ['pandas/core/indexing.py'])]),
    ("cat > /tmp/repro.py <<'EOF'\n"
     'import tracemalloc\n'
     'import numpy as np\n'
     'import pandas as pd\n'
     'n = 100_000\n'
     'df = pd.DataFrame({c: np.zeros(n) for c in "abcd"})\n'
     'res = df.loc[0, ["a", "b", "d"]]\n'
     'print(getattr(res.values.base, "shape", None))\n'
     'tracemalloc.start()\n'
     'results = [df.loc[0, ["a", "b", "d"]] for _ in range(100)]\n'
     'print(f"{tracemalloc.get_traced_memory()[0] / 2**20:.0f} MiB")\n'
     'EOF\n'
     'timeout 600 python -I /tmp/repro.py 2>&1 | tail -5',
     [('write_outside', 'cat', ['/tmp/repro.py']),
      ('run', 'python', ['/tmp/repro.py']),
      ('filter', 'tail', [])]),
    ('sed -n 1199,1240p pandas/core/indexing.py && echo ---- && sed -n 1790,1870p '
     'pandas/core/indexing.py',
     [('view', 'sed -n', ['pandas/core/indexing.py']),
      ('other', 'echo', []),
      ('view', 'sed -n', ['pandas/core/indexing.py'])]),
    ('sed -n 1240,1260p pandas/core/indexing.py && echo ---- && sed -n 1356,1400p '
     'pandas/core/indexing.py && echo ---- && grep -n "def xs" -A5 pandas/core/frame.py | head -20',
     [('view', 'sed -n', ['pandas/core/indexing.py']),
      ('other', 'echo', []),
      ('view', 'sed -n', ['pandas/core/indexing.py']),
      ('other', 'echo', []),
      ('search_content', 'grep', ['pandas/core/frame.py']),
      ('filter', 'head', [])]),
    ('sed -n 1260,1280p pandas/core/indexing.py && echo ---- && sed -n 1870,1890p '
     'pandas/core/indexing.py && echo ---- && grep -n "def _getitem_tuple" -A30 '
     'pandas/core/indexing.py | sed -n 1,5p; sed -n 2371,2395p pandas/core/indexing.py',
     [('view', 'sed -n', ['pandas/core/indexing.py']),
      ('other', 'echo', []),
      ('view', 'sed -n', ['pandas/core/indexing.py']),
      ('other', 'echo', []),
      ('search_content', 'grep', ['pandas/core/indexing.py']),
      ('filter', 'sed -n', []),
      ('view', 'sed -n', ['pandas/core/indexing.py'])]),
    ('grep -n "def xs" pandas/core/generic.py && grep -n "fast_xs\\|_ixs\\|is_copy\\|def xs" '
     'pandas/core/generic.py | head -40; echo ----; grep -n "def fast_xs" -A30 '
     'pandas/core/internals/managers.py | head -45',
     [('search_content', 'grep', ['pandas/core/generic.py']),
      ('search_content', 'grep', ['pandas/core/generic.py']),
      ('filter', 'head', []),
      ('other', 'echo', []),
      ('search_content', 'grep', ['pandas/core/internals/managers.py']),
      ('filter', 'head', [])]),
    ('sed -n 4310,4345p pandas/core/generic.py; echo ----; grep -n "def _ixs" -A45 '
     'pandas/core/frame.py | head -60',
     [('view', 'sed -n', ['pandas/core/generic.py']),
      ('other', 'echo', []),
      ('search_content', 'grep', ['pandas/core/frame.py']),
      ('filter', 'head', [])]),
    ('grep -n "ABCSeries\\|^from pandas.core.dtypes.common import\\|is_list_like," '
     'pandas/core/indexing.py | head -5; timeout 900 python -I /tmp/repro.py 2>&1 | tail -3; '
     'python -c "\n'
     'import pandas as pd, numpy as np\n'
     "df = pd.DataFrame({'a':[1,2],'b':[3.0,4.0],'c':['x','y']})\n"
     "print(df.loc[0,['a','c']], df.iloc[1,[0,2]].dtype, df.loc[1,['b','a']].values.base)\n"
     '"',
     [('search_content', 'grep', ['pandas/core/indexing.py']),
      ('filter', 'head', []),
      ('run', 'python', ['/tmp/repro.py']),
      ('filter', 'tail', []),
      ('run', 'python', [])]),
    ('timeout 1500 python -m pytest pandas/tests/indexing -q -x -p no:cacheprovider 2>&1 | tail '
     '-15',
     [('test', 'python -m pytest', ['pandas/tests/indexing']),
      ('filter', 'tail', [])]),
    ('head -20 pandas/tests/indexing/test_indexing.py | grep -n "import" ; tail -3 '
     'pandas/tests/indexing/test_indexing.py; cat >> pandas/tests/indexing/test_indexing.py '
     "<<'EOF'\n"
     '\n'
     '\n'
     'def test_loc_iloc_row_and_list_cols_no_view_of_temporary():\n'
     '    # GH#issue: df.loc[row, list_of_cols] must not return a view into the\n'
     '    # temporary (len(cols), len(df)) array created by the column selection.\n'
     '    df = DataFrame({c: np.zeros(1000) for c in "abcd"})\n'
     '    for res in (df.loc[0, ["a", "b", "d"]], df.iloc[0, [0, 1, 3]]):\n'
     '        assert res.shape == (3,)\n'
     '        assert res.values.base is None\n'
     'EOF\n'
     'timeout 1500 python -m pytest pandas/tests/indexing/test_indexing.py -q -p no:cacheprovider '
     '-k no_view_of_temporary 2>&1 | tail -2; timeout 1500 python -m pytest '
     'pandas/tests/frame/indexing pandas/tests/series/indexing -q -p no:cacheprovider 2>&1 | tail '
     '-2',
     [('view', 'head', ['pandas/tests/indexing/test_indexing.py']),
      ('filter', 'grep', []),
      ('view', 'tail', ['pandas/tests/indexing/test_indexing.py']),
      ('edit', 'cat', ['pandas/tests/indexing/test_indexing.py']),
      ('test', 'python -m pytest', ['pandas/tests/indexing/test_indexing.py']),
      ('filter', 'tail', []),
      ('test', 'python -m pytest', ['pandas/tests/frame/indexing', 'pandas/tests/series/indexing']),
      ('filter', 'tail', [])]),
    ("python - <<'EOF'\n"
     'p="pandas/tests/indexing/test_indexing.py"\n'
     's=open(p).read()\n'
     's=s.replace("    # GH#issue: df.loc[row, list_of_cols] must not return a view into the\\n    '
     '# temporary (len(cols), len(df)) array created by the column selection.\\n    df = '
     'DataFrame(","    # df.loc[row, list_of_cols] must not return a view into the temporary\\n    '
     '# (len(cols), len(df)) array created by the column selection.\\n    df = pd.DataFrame(")\n'
     'open(p,"w").write(s)\n'
     'EOF\n'
     'timeout 900 python -m pytest pandas/tests/indexing/test_indexing.py -q -p no:cacheprovider '
     '-k no_view_of_temporary 2>&1 | tail -1; git diff --stat',
     [('edit_script', 'python', ['pandas/tests/indexing/test_indexing.py']),
      ('test', 'python -m pytest', ['pandas/tests/indexing/test_indexing.py']),
      ('filter', 'tail', []),
      ('git', 'git diff', [])]),
    ('timeout 900 python -m pytest pandas/tests/indexing/test_indexing.py -q -p no:cacheprovider '
     '-k no_view_of_temporary 2>&1 | grep -E "Error|assert" | head -8',
     [('test', 'python -m pytest', ['pandas/tests/indexing/test_indexing.py']),
      ('filter', 'grep', []),
      ('filter', 'head', [])]),
    ('python -c "\n'
     'import pandas as pd, numpy as np\n'
     "df = pd.DataFrame({c: np.zeros(1000) for c in 'abcd'})\n"
     "r=df.loc[0,['a','b','d']]; print(type(r.values.base), getattr(r.values.base,'shape',None), "
     'r.values.flags.owndata)\n'
     "r=df.iloc[0,[0,1,3]]; print(getattr(r.values.base,'shape',None))\n"
     '"',
     [('run', 'python', [])]),
    ("python - <<'EOF'\n"
     'p="pandas/tests/indexing/test_indexing.py"\n'
     's=open(p).read()\n'
     's=s.replace("        assert res.values.base is None\\n","        # the backing array holds '
     'only the 3 selected values, not (3, 1000)\\n        base = res.values.base\\n        assert '
     'base is None or base.shape == (3,)\\n")\n'
     'open(p,"w").write(s)\n'
     'EOF\n'
     'timeout 900 python -m pytest pandas/tests/indexing -q -p no:cacheprovider 2>&1 | tail -1; '
     'git diff pandas/core/indexing.py',
     [('edit_script', 'python', ['pandas/tests/indexing/test_indexing.py']),
      ('test', 'python -m pytest', ['pandas/tests/indexing']),
      ('filter', 'tail', []),
      ('view_git', 'git diff', ['pandas/core/indexing.py'])]),
    # pandas-dev__pandas-66227
    ('git log --oneline | head -3 && grep -n "__mul__\\|_scalar_multiply\\|def '
     '__rmul__\\|_scalar_divlike\\|checked_add\\|overflow" pandas/core/arrays/timedeltas.py | head '
     '-60',
     [('git', 'git log', []),
      ('filter', 'head', []),
      ('search_content', 'grep', ['pandas/core/arrays/timedeltas.py']),
      ('filter', 'head', [])]),
    ('sed -n 440,500p pandas/core/arrays/timedeltas.py && grep -n "def sum\\|_reduce\\|def '
     '_accumulate\\|checked" pandas/core/arrays/timedeltas.py | head; grep -rn "def '
     'checked_add_with_arr" -A3 pandas/core/algorithms.py pandas/core/missing.py '
     'pandas/core/ops/*.py | head -20',
     [('view', 'sed -n', ['pandas/core/arrays/timedeltas.py']),
      ('search_content', 'grep', ['pandas/core/arrays/timedeltas.py']),
      ('filter', 'head', []),
      ('search_content', 'grep', ['pandas/core/algorithms.py', 'pandas/core/missing.py', 'pandas/core/ops/*.py']),
      ('filter', 'head', [])]),
    ('python -c "\n'
     'import pandas as pd, traceback\n'
     "x = pd.Series([pd.Timedelta(100000, 'days'), pd.Timedelta(100000, 'days')])\n"
     "for f in [lambda: x.sum(), lambda: pd.Timedelta(100000,'days')*2, lambda: x+x, lambda: x*2, "
     'lambda: x._values*2]:\n'
     '    try: print(f())\n'
     '    except Exception as e: print(type(e), e)\n'
     '" 2>&1 | tail -20; grep -n "checked_add_with_arr\\|def _sum\\|def _reduce\\|overflow" '
     'pandas/core/arrays/datetimelike.py | head -30',
     [('run', 'python', []),
      ('filter', 'tail', []),
      ('search_content', 'grep', ['pandas/core/arrays/datetimelike.py']),
      ('filter', 'head', [])]),
    ('python -c "\n'
     'import pandas as pd, numpy as np\n'
     'print(pd.__version__)\n'
     "x = pd.Series(pd.to_timedelta([pd.Timedelta(100000, 'days').value]*2, unit='ns'))\n"
     "x = pd.Series(pd.array([pd.Timedelta(100000, 'days')]*2, dtype='timedelta64[ns]'))\n"
     'print(x.dtype)\n'
     "for f in [lambda: x.sum(), lambda: pd.Timedelta(100000,'days')*2, lambda: x+x, lambda: x*2, "
     'lambda: x.cumsum()]:\n'
     '    try: print(f())\n'
     '    except Exception as e: print(type(e), e)\n'
     '" 2>&1 | tail -30',
     [('run', 'python', []),
      ('filter', 'tail', [])]),
    ('python -c "\n'
     'import pandas as pd, traceback\n'
     "x = pd.Series(pd.array([pd.Timedelta(100000, 'days')]*2, dtype='timedelta64[ns]'))\n"
     'try: x.sum()\n'
     'except Exception: traceback.print_exc()\n'
     '" 2>&1 | tail -25; grep -rn "overflow in timedelta operation\\|Overflow in int64 addition" '
     'pandas/_libs pandas/core | head; grep -rn "def __mul__" -A30 '
     'pandas/_libs/tslibs/timedeltas.pyx | head -50',
     [('run', 'python', []),
      ('filter', 'tail', []),
      ('search_content', 'grep', ['pandas/_libs', 'pandas/core']),
      ('filter', 'head', []),
      ('search_content', 'grep', ['pandas/_libs/tslibs/timedeltas.pyx']),
      ('filter', 'head', [])]),
    ('grep -rn "OutOfBoundsTimedelta" pandas/tests | grep -i "sum\\|mul\\|overflow" | head -20; sed '
     '-n 360,385p pandas/core/nanops.py; grep -rn "Overflow" '
     'pandas/tests/arithmetic/test_timedelta64.py | head -30',
     [('search_content', 'grep', ['pandas/tests']),
      ('filter', 'grep', []),
      ('filter', 'head', []),
      ('view', 'sed -n', ['pandas/core/nanops.py']),
      ('search_content', 'grep', ['pandas/tests/arithmetic/test_timedelta64.py']),
      ('filter', 'head', [])]),
    ('grep -rn "overflow in timedelta\\|43178" pandas/tests | head; sed -n 735,760p '
     'pandas/tests/arithmetic/test_timedelta64.py',
     [('search_content', 'grep', ['pandas/tests']),
      ('filter', 'head', []),
      ('view', 'sed -n', ['pandas/tests/arithmetic/test_timedelta64.py'])]),
    ('sed -n 105,130p /testbed/pandas/tests/series/test_reductions.py',
     [('view', 'sed -n', ['pandas/tests/series/test_reductions.py'])]),
    ('sed -n 1,60p pandas/core/arrays/timedeltas.py | grep -n "import\\|iNaT\\|NaT" ; grep -n "^def '
     '\\|^class " pandas/core/arrays/timedeltas.py',
     [('view', 'sed -n', ['pandas/core/arrays/timedeltas.py']),
      ('filter', 'grep', []),
      ('search_content', 'grep', ['pandas/core/arrays/timedeltas.py'])]),
    ('python -c "\n'
     'import pandas as pd, numpy as np\n'
     "x = pd.Series(pd.array([pd.Timedelta(100000, 'days')]*2, dtype='timedelta64[ns]'))\n"
     'for f in [lambda: x*2, lambda: 2*x, lambda: x*1.5, lambda: x*np.array([1,2]), lambda: '
     'x*-3]:\n'
     '    try: print(f().tolist())\n'
     '    except Exception as e: print(type(e).__name__, e)\n'
     "y = pd.Series(pd.to_timedelta([1,None,-5], unit='ns'))\n"
     'print((y*np.iinfo(np.int64).max).tolist() if False else (y*3).tolist(), (y*0).tolist(), '
     '(y*-1).tolist(), (y*0.5).tolist())\n'
     "print((pd.Series(pd.to_timedelta([np.iinfo(np.int64).max//2 ], unit='ns'))*2).tolist())\n"
     '" 2>&1 | tail -12 && python -m pytest -q -x pandas/tests/arithmetic/test_timedelta64.py '
     'pandas/tests/scalar/timedelta pandas/tests/series/test_reductions.py '
     'pandas/tests/arrays/test_timedeltas.py -p no:cacheprovider 2>&1 | tail -15',
     [('run', 'python', []),
      ('filter', 'tail', []),
      ('test', 'python -m pytest', ['pandas/tests/arithmetic/test_timedelta64.py',
                                    'pandas/tests/scalar/timedelta',
                                    'pandas/tests/series/test_reductions.py',
                                    'pandas/tests/arrays/test_timedeltas.py']),
      ('filter', 'tail', [])]),
    ("cat >> pandas/tests/arithmetic/test_timedelta64.py <<'EOF'\n"
     '\n'
     '\n'
     'def test_td64_mul_overflow_raises():\n'
     '    # GH#48873 (issue): multiplying timedelta64[ns] values past int64 range\n'
     '    # should raise OverflowError, consistent with addition, rather than\n'
     '    # silently wrapping around.\n'
     '    ser = Series(pd.array([pd.Timedelta(100000, "days")] * 2, dtype="timedelta64[ns]"))\n'
     '    msg = "Overflow in int64 multiplication"\n'
     '    with pytest.raises(OverflowError, match=msg):\n'
     '        ser * 2\n'
     '    with pytest.raises(OverflowError, match=msg):\n'
     '        2 * ser\n'
     '    with pytest.raises(OverflowError, match=msg):\n'
     '        ser * 1.5\n'
     '    with pytest.raises(OverflowError, match=msg):\n'
     '        ser * np.array([1, 2])\n'
     '\n'
     '    # NaT and non-overflowing products are still fine\n'
     '    ser = Series(pd.to_timedelta([1, None, -5], unit="ns"))\n'
     '    result = ser * -3\n'
     '    expected = Series(pd.to_timedelta([-3, None, 15], unit="ns"))\n'
     '    tm.assert_series_equal(result, expected)\n'
     'EOF\n'
     'grep -n "^import\\|^from" pandas/tests/arithmetic/test_timedelta64.py | head -30',
     [('edit', 'cat', ['pandas/tests/arithmetic/test_timedelta64.py']),
      ('search_content', 'grep', ['pandas/tests/arithmetic/test_timedelta64.py']),
      ('filter', 'head', [])]),
    ("sed -i 's|    # GH#48873 (issue): multiplying timedelta64\\[ns\\] values past int64 range|    "
     "# Multiplying timedelta64[ns] values past the int64 range|' "
     "pandas/tests/arithmetic/test_timedelta64.py && sed -i 's|    # should raise OverflowError, "
     'consistent with addition, rather than|    # should raise OverflowError, consistent with '
     'addition, rather than|\' pandas/tests/arithmetic/test_timedelta64.py && grep -n "Multiplying '
     'timedelta64" -A3 pandas/tests/arithmetic/test_timedelta64.py && python -m pytest -q '
     'pandas/tests/arithmetic/test_timedelta64.py -k mul_overflow -p no:cacheprovider 2>&1 | tail '
     '-2 && python -m pytest -q pandas/tests/arithmetic pandas/tests/series '
     'pandas/tests/frame/test_arithmetic.py pandas/tests/arrays pandas/tests/scalar/timedelta '
     'pandas/tests/reductions -p no:cacheprovider -x -n 4 2>&1 | tail -3',
     [('edit', 'sed -i', ['pandas/tests/arithmetic/test_timedelta64.py']),
      ('edit', 'sed -i', ['pandas/tests/arithmetic/test_timedelta64.py']),
      ('search_content', 'grep', ['pandas/tests/arithmetic/test_timedelta64.py']),
      ('test', 'python -m pytest', ['pandas/tests/arithmetic/test_timedelta64.py']),
      ('filter', 'tail', []),
      ('test', 'python -m pytest', ['pandas/tests/arithmetic',
                                    'pandas/tests/series',
                                    'pandas/tests/frame/test_arithmetic.py',
                                    'pandas/tests/arrays',
                                    'pandas/tests/scalar/timedelta',
                                    'pandas/tests/reductions']),
      ('filter', 'tail', [])]),
    ('(ruff check pandas/core/arrays/timedeltas.py pandas/tests/arithmetic/test_timedelta64.py '
     '2>&1 | tail -3; ruff format --check pandas/core/arrays/timedeltas.py '
     'pandas/tests/arithmetic/test_timedelta64.py 2>&1 | tail -2); git status --short',
     [('run', 'ruff', ['pandas/core/arrays/timedeltas.py', 'pandas/tests/arithmetic/test_timedelta64.py']),
      ('filter', 'tail', []),
      ('run', 'ruff', ['pandas/core/arrays/timedeltas.py', 'pandas/tests/arithmetic/test_timedelta64.py']),
      ('filter', 'tail', []),
      ('git', 'git status', [])]),
]


@pytest.mark.parametrize("command, expected", TRANSCRIPT)
def test_transcript_commands(command, expected):
    assert _summary(command) == expected


def test_table_holds_every_call_of_both_transcripts():
    assert [c for c, _ in TRANSCRIPT] == _bash_calls(FIXTURE_70742) + _bash_calls(FIXTURE_66227)


# ---- count_steps

def _stream(*turns) -> list[dict]:
    """Events of a made-up run. Each turn is a list of (tool name, input, result text)."""
    events = []
    for n, calls in enumerate(turns, start=1):
        for k, (name, args, _) in enumerate(calls):
            events.append({"type": "assistant", "parent_tool_use_id": None, "message": {
                "id": f"m{n}", "content": [{"type": "tool_use", "id": f"t{n}-{k}", "name": name, "input": args}]}})
        for k, (_, _, result) in enumerate(calls):
            events.append({"type": "user", "parent_tool_use_id": None, "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{n}-{k}", "content": result}]}})
    return events


def _bash(command: str, result: str = "") -> tuple:
    return ("Bash", {"command": command}, result)


GOLD = ["pandas/core/indexing.py"]


def _gold(events, gold=GOLD) -> dict:
    return count_steps(events, gold)["gold"][gold[0]]


def test_gold_surfaced_without_opened():
    events = _stream([_bash("grep -rn _getitem_lowerdim pandas", "pandas/core/indexing.py:1199:    def _getitem")],
                     [_bash("echo done")])
    assert _gold(events) == {"surfaced": 1, "opened": None, "edited": None, "named_by_agent": None}
    steps = count_steps(events, GOLD)
    assert steps["gold_surfaced"] and not steps["gold_opened"] and steps["gold_opened_share"] == 0.0


def test_gold_opened_is_also_surfaced():
    # sed -n prints the lines without the path. Version 2 left surfaced empty here.
    events = _stream([_bash("echo start")], [_bash("sed -n 1,5p pandas/core/indexing.py", "import numpy")])
    assert _gold(events) == {"surfaced": 2, "opened": 2, "edited": None, "named_by_agent": 2}


def test_gold_path_inside_a_longer_path_does_not_match():
    longer = ("tests/pandas/core/indexing.py:3: x\npandas/core/indexing.pyi\nxpandas/core/indexing.py\n"
              "pandas/core/indexing.py.orig\npandas/core/indexing.py/x")
    events = _stream([_bash("grep -rn x .", longer)], [_bash("cat pandas/core/indexing_utils.py")])
    assert _gold(events) == {"surfaced": None, "opened": None, "edited": None, "named_by_agent": None}
    # A gold file at the top level is not found inside a path in a folder.
    events = _stream([_bash("cat pandas/indexing.py", "see pandas/indexing.py")])
    assert _gold(events, ["indexing.py"])["surfaced"] is None
    # Diff headers and the end of a sentence still match.
    events = _stream([_bash("git diff", "diff --git a/pandas/core/indexing.py b/pandas/core/indexing.py")],
                     [_bash("echo", "I changed pandas/core/indexing.py.")])
    assert _gold(events)["surfaced"] == 1


def test_gold_path_with_the_repo_root():
    events = _stream([_bash("python /tmp/r.py", 'File "/testbed/pandas/core/indexing.py", line 3, in f')],
                     [("Read", {"file_path": "/testbed/pandas/core/indexing.py"}, "1\timport x\n2\timport y")],
                     [("Edit", {"file_path": "/testbed/pandas/core/indexing.py", "old_string": "x",
                                "new_string": "y"}, "ok")])
    assert _gold(events) == {"surfaced": 1, "opened": 2, "edited": 3, "named_by_agent": 2}
    assert count_steps(events, ["/testbed/pandas/core/indexing.py"])["gold_files"] == GOLD


def test_gold_opened_after_cd():
    events = _stream([_bash("cd pandas/core && sed -n 1,5p indexing.py", "import numpy")])
    assert _gold(events)["opened"] == 1 and _gold(events)["named_by_agent"] == 1


def test_cd_carries_to_the_next_call_inside_the_repo():
    events = _stream([_bash("cd pandas/core")], [_bash("cat indexing.py")], [_bash("cd /tmp")],
                     [_bash("cat pandas/core/indexing.py")])
    steps = count_steps(events, GOLD)
    assert steps["gold"][GOLD[0]]["opened"] == 2
    assert [c["cwd"] for c in steps["commands"]] == [".", "pandas/core", "pandas/core", "."]


def test_turn_marks_and_edits():
    events = _stream([_bash("cat > /tmp/repro.py <<'EOF'\nprint(1)\nEOF\npython /tmp/repro.py")],
                     [_bash("python -m pytest pandas/tests -x 2>&1 | tail -3", "1 passed")],
                     [("mcp__codemem__search", {"query": "loc"}, "pandas/core/indexing.py:10")],
                     [_bash("sed -i 's/a/b/' pandas/core/indexing.py")],
                     [("Write", {"file_path": "/testbed/pandas/new.py", "content": "x"}, "ok")])
    steps = count_steps(events, GOLD)
    assert steps["first_edit_turn"] == 4 and steps["turns_before_first_edit"] == 3  # /tmp does not count
    assert (steps["first_test_turn"], steps["first_mcp_turn"], steps["first_codemem_turn"]) == (2, 3, 3)
    assert steps["codemem_calls"] == 1 and steps["mcp_tools"] == {"mcp__codemem__search": 1}
    assert steps["actions"]["mcp"] == 1 and steps["tests_run"] == 1
    assert steps["edits"] == {"tool": 1, "shell": 1, "script": 0, "outside": 1, "reverts": 0,
                              "files_edited": ["pandas/core/indexing.py", "pandas/new.py"], "files_edited_guess": []}
    assert steps["gold"][GOLD[0]] == {"surfaced": 3, "opened": None, "edited": 4, "named_by_agent": 4}


def test_lines_viewed():
    events = _stream([_bash("sed -n 1,40p a.py && echo ---- && head -5 b.py")],
                     [("Read", {"file_path": "/testbed/c.py", "offset": 10, "limit": 25}, "10\tx\n11\ty")],
                     [_bash("cat d.py", "a\nb\nc")],
                     [_bash("cat e.py f.py", "a\nb")],
                     [_bash("head -20 g.py | grep import")])
    views = count_steps(events, GOLD)["views"]
    # sed and head give their ranges, Read the lines it returned, and the one whole-file view of a call the
    # lines of the result. The head into a grep shows an unknown part of its 20 lines.
    assert views == {"count": 6, "files_viewed": ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py"],
                     "lines_viewed": 40 + 5 + 2 + 3 + 2, "whole_file_views": 2, "lines_unknown": 1}


def test_long_command_is_cut():
    steps = count_steps(_stream([_bash("echo " + "x" * 3000)]), GOLD)
    entry, = steps["commands"]
    assert len(entry["command"]) == 2000 and entry["cut"] and entry["simple"] == [["other", "echo", []]]


def test_counts_of_the_70742_run():
    steps = count_steps(e2e_steps.parse_stream(FIXTURE_70742)["events"], GOLD_70742)
    assert (steps["turns"], steps["bash_calls"], steps["bash_commands"]) == (17, 14, 61)
    assert steps["tool_calls"] == {"Bash": 14, "Edit": 2, "Read": 1}
    assert steps["searches"] == {"content": 8, "files": 0, "programs": {"grep": 8}}
    assert steps["views"] == {"count": 11, "lines_viewed": 320, "whole_file_views": 0, "lines_unknown": 1,
                              "files_viewed": ["pandas/core/indexing.py", "pandas/core/generic.py",
                                               "pandas/tests/indexing/test_indexing.py"]}
    assert steps["edits"] == {"tool": 2, "shell": 1, "script": 2, "outside": 1, "reverts": 0,
                              "files_edited_guess": [],
                              "files_edited": ["pandas/core/indexing.py", "pandas/tests/indexing/test_indexing.py"]}
    assert (steps["actions"]["other"], steps["actions"]["unparsed"], steps["tests_run"]) == (7, 0, 6)
    # Checked by hand against the stream. Turn 1 greps the file by name (grep prints no path for one file, so
    # version 2 said surfaced 9), turn 2 views it with sed -n, the Edit of turn 7 fails (the text did not match),
    # turn 8 reads it, the Edit of turn 9 works and its result shows the path.
    assert steps["gold"]["pandas/core/indexing.py"] == {"surfaced": 1, "opened": 2, "edited": 7, "named_by_agent": 1}
    assert (steps["first_edit_turn"], steps["turns_before_first_edit"], steps["first_test_turn"]) == (7, 6, 11)
    assert steps["gold_file_read"] and steps["first_gold_read_turn"] == 2


def test_counts_of_the_66227_run():
    steps = count_steps(e2e_steps.parse_stream(FIXTURE_66227)["events"], GOLD_66227)
    assert (steps["turns"], steps["bash_calls"], steps["bash_commands"]) == (17, 13, 53)
    assert steps["searches"] == {"content": 12, "files": 0, "programs": {"grep": 12}}
    assert steps["views"]["files_viewed"] == ["pandas/core/arrays/timedeltas.py", "pandas/core/nanops.py",
                                              "pandas/tests/arithmetic/test_timedelta64.py",
                                              "pandas/tests/series/test_reductions.py"]
    assert (steps["views"]["count"], steps["views"]["lines_viewed"]) == (5, 139)
    assert (steps["edits"]["tool"], steps["edits"]["shell"], steps["edits"]["script"]) == (3, 3, 0)
    # Checked by hand: turn 1 greps the file by name, turn 2 views it with sed -n, the traceback of turn 5 shows
    # its path (version 2 said surfaced 5), and the first Edit is at turn 10.
    assert steps["gold"]["pandas/core/arrays/timedeltas.py"] == {"surfaced": 1, "opened": 2, "edited": 10,
                                                                 "named_by_agent": 1}
    assert (steps["first_edit_turn"], steps["first_test_turn"]) == (10, 13)


# ---- faults of version 2, from commands of the Haiku runs of 2026-11-25 (pandas 70742, playwright 42503)

GOLD_42503 = ["packages/playwright/src/mcp/test/browserBackend.ts"]
TASK_OUTPUT = "/tmp/claude-1000/-testbed/e0c84efe-d5ed-4bfa-bede-ed0bbcc9ea46/tasks/bfn569r0d.output"


def test_grep_in_the_gold_file_surfaces_it():
    # pilot-haiku-1, pandas 70742, tool, turn 1. grep on one file prints no path. Version 2: surfaced 16, opened 2.
    command = ('git status --short | head && python -c "\nimport numpy as np, pandas as pd\nn=100_000\n'
               'df = pd.DataFrame({c: np.zeros(n) for c in \'abcd\'})\nres = df.loc[0, [\'a\',\'b\',\'d\']]\n'
               'print(getattr(res.values.base,\'shape\',None), pd.__version__)\nres = df.iloc[0, [0,1,3]]\n'
               'print(getattr(res.values.base,\'shape\',None))\n" 2>&1 | tail -3; grep -n "_multi_take\\\\|'
               'def _getitem_tuple_same_dim\\\\|def _getitem_lowerdim\\\\|def _handle_lowerdim_multi_index_axis0" '
               'pandas/core/indexing.py | head -30')
    result = ("(3, 100000) 3.2.0.dev0\n(3, 100000)\n1171:    def _getitem_tuple_same_dim(self, tup: tuple[Any, ...]):\n"
              "1199:    def _getitem_lowerdim(self, tup: tuple[Any, ...]):\n")
    events = _stream([_bash(command, result)], [_bash("sed -n 1199,1260p pandas/core/indexing.py", "    def x")])
    assert _gold(events) == {"surfaced": 1, "opened": 2, "edited": None, "named_by_agent": 1}
    # A grep through a folder that holds the file does not surface it when the file is not in the result.
    events = _stream([_bash('grep -rn "fast_xs" pandas --include=*.py | head -20', "pandas/core/apply.py:1546: x")])
    assert _gold(events)["surfaced"] is None


def test_read_surfaces_the_file():
    # vague-l2-1, pandas 70742, tool, turn 3: the Read result has numbered lines and no path. Version 2: surfaced
    # 4, opened 3.
    events = _stream([_bash("git status --short | head")],
                     [_bash("cat > /tmp/repro.py <<'EOF'\nprint(1)\nEOF\npython /tmp/repro.py")],
                     [("Read", {"file_path": "/testbed/pandas/core/indexing.py", "offset": 1199, "limit": 70},
                       "  1199\t    def _getitem_lowerdim(self, tup):")])
    assert _gold(events)["surfaced"] == 3 and _gold(events)["opened"] == 3


def test_listing_of_the_folder_surfaces_the_file():
    # vague2-l2-1, playwright 42503, tool, turns 3 and 4. ls prints the bare name; after the cd, cat names it
    # relative to the folder. Version 2: surfaced 5, opened 4.
    turn3 = "cat packages/playwright/src/mcp/test/testTools.ts; ls packages/playwright/src/mcp/test/"
    turn4 = ('cd packages/playwright/src/mcp/test; cat browserBackend.ts; grep -rn "pause\\\\|Pause" '
             '../../../../playwright/src/mcp/test/testContext.ts ../../../../playwright/src/mcp/test/testBackend.ts '
             '| head -40')
    listing = "/**\n * Copyright (c) Microsoft Corporation.\n */\nbrowserBackend.ts\ntestBackend.ts\ntestContext.ts\n"
    events = _stream([_bash(turn3, listing)], [_bash(turn4, "/**\n * Copyright")])
    assert _gold(events, GOLD_42503) == {"surfaced": 1, "opened": 2, "edited": None, "named_by_agent": 2}
    # The same name in a listing of another folder is not the gold file.
    events = _stream([_bash("ls packages/playwright/src/mcp/browser", "browserBackend.ts\n")])
    assert _gold(events, GOLD_42503)["surfaced"] is None
    # grep -rn after a cd prints paths relative to the folder.
    events = _stream([_bash("cd packages/playwright/src/mcp && grep -rn pause .",
                            "./test/browserBackend.ts:12:  pause()")])
    assert _gold(events, GOLD_42503)["surfaced"] == 1 and _gold(events, GOLD_42503)["opened"] is None


def test_grep_in_a_log_in_tmp_is_not_a_code_search():
    # pilot-haiku-1, pandas 70742, tool, turns 46 and 47.
    assert _summary("timeout 110 bash -c 'until grep -q \"^EXIT\" /tmp/wide_tests.log; do sleep 5; done' ; "
                    "tail -3 /tmp/wide_tests.log") == [
        ("read_outside", "grep", ["/tmp/wide_tests.log"]), ("other", "sleep", []),
        ("read_outside", "tail", ["/tmp/wide_tests.log"])]
    assert _summary('grep -E "passed|failed|EXIT|^FAILED" /tmp/wide_tests.log | tail -8') == [
        ("read_outside", "grep", ["/tmp/wide_tests.log"]), ("filter", "tail", [])]
    # vague-l2-1, playwright 42503, tool, turn 28: a cache folder outside the repo.
    assert _summary("ls ~/.cache/ms-playwright 2>/dev/null") == [("read_outside", "ls", ["~/.cache/ms-playwright"])]
    # A search that holds the repo, or a search in a repo file and a log, is still a code search.
    assert _summary("find / -name indexing.py")[0][0] == "search_files"
    assert _summary("grep -n x pandas/a.py /tmp/log")[0][0] == "search_content"
    assert _summary("cd /tmp && grep -rn EXIT")[1] == ("read_outside", "grep", [])
    steps = count_steps(_stream([_bash('grep -E "passed|failed" /tmp/wide_tests.log | tail -8')]), GOLD)
    assert steps["searches"]["content"] == 0 and steps["actions"]["read_outside"] == 1


def test_blocked_call_is_not_done():
    # pilot-haiku-1, pandas 70742, tool, turn 35: Claude Code blocked the call; turn 36 runs the tail alone.
    blocked = ("<tool_use_error>Blocked: sleep 100 followed by: tail -c 400 " + TASK_OUTPUT + ". To wait for a "
               "condition, use Monitor with an until-loop (e.g. `until <check>; do sleep 2; done`).</tool_use_error>")
    events = _stream([_bash("sleep 100; tail -c 400 " + TASK_OUTPUT, blocked)],
                     [_bash("tail -c 400 " + TASK_OUTPUT, "2 failed in 0.11s")])
    steps = count_steps(events, GOLD)
    assert (steps["bash_calls"], steps["blocked_calls"]) == (2, 1)
    assert steps["actions"]["read_outside"] == 1 and steps["actions"]["other"] == 0
    assert steps["commands"][0]["blocked"] and "blocked" not in steps["commands"][1]
    # Nothing of a blocked call counts: not its test, its edit, its cd, nor the path that its error text repeats.
    edit = "sed -i 's/a/b/' pandas/core/indexing.py && python -m pytest pandas/tests/indexing"
    events = _stream([_bash("cd pandas", "<tool_use_error>Blocked: cd</tool_use_error>")],
                     [_bash(edit, "<tool_use_error>Blocked: " + edit + "</tool_use_error>")],
                     [_bash("cat core/indexing.py")])
    steps = count_steps(events, GOLD)
    assert (steps["first_edit_turn"], steps["first_test_turn"], steps["tests_run"]) == (None, None, 0)
    assert steps["gold"][GOLD[0]] == {"surfaced": None, "opened": None, "edited": None, "named_by_agent": 2}
    # An Edit whose old text is not found is not blocked: it counts as an edit, as in version 2.
    failed = ("Edit", {"file_path": "/testbed/pandas/core/indexing.py", "old_string": "x", "new_string": "y"},
              "<tool_use_error>String to replace not found in file.\nString: x</tool_use_error>")
    steps = count_steps(_stream([failed]), GOLD)
    assert steps["first_edit_turn"] == 1 and steps["blocked_calls"] == 0
    denied = ("Write", {"file_path": "/testbed/a.py", "content": "x"},
              "<tool_use_error>Permission to use Write has been denied.</tool_use_error>")
    assert count_steps(_stream([denied]), GOLD)["blocked_calls"] == 1


def test_dev_null_and_task_output_are_not_views():
    # vague-l1-1, pandas 70742, tool, turn 2 (the last line of the call).
    assert _summary('python /tmp/repro.py; grep -n "" /dev/null; ls pandas/core/indexing.py') == [
        ("run", "python", ["/tmp/repro.py"]), ("other", "grep", []),
        ("search_files", "ls", ["pandas/core/indexing.py"])]
    # pandas 68090 (transcript note 1); not in the 14 runs of 70742 and 42503.
    assert _summary("sed -n 1,5p /dev/null")[0][0] == "other"
    # grep FILE /dev/null makes grep print the file name: the repo file stays.
    assert _summary("grep -n foo pandas/a.py /dev/null") == [("search_content", "grep", ["pandas/a.py"])]
    # pilot-haiku-1, pandas 70742, tool, turn 36: the output file of a command in the background.
    a = _one("tail -c 400 " + TASK_OUTPUT)
    assert (a.kind, a.outside, a.lines) == ("read_outside", (TASK_OUTPUT,), None)
    # pilot-haiku-1, playwright 42503, tool, turn 24: a log of the agent.
    assert _summary("cat /tmp/dbg.log") == [("read_outside", "cat", ["/tmp/dbg.log"])]
    # Claude Code tells the agent to Read the output file; not seen in the 14 runs.
    steps = count_steps(_stream([("Read", {"file_path": TASK_OUTPUT}, "1\t2 failed")]), GOLD)
    assert steps["views"]["count"] == 0 and steps["actions"]["read_outside"] == 1


def test_writes_outside_the_repo_and_reverts_are_not_edits():
    # vague-l1-1, pandas 70742, tool, turn 2: a script in /tmp.
    assert _summary("cat > /tmp/repro.py <<'EOF'\nimport numpy as np, pandas as pd\nEOF\npython /tmp/repro.py") == [
        ("write_outside", "cat", ["/tmp/repro.py"]), ("run", "python", ["/tmp/repro.py"])]
    # pilot-haiku-1, pandas 70742, tool, turn 41: echo >> to a log.
    command = ("(timeout 1500 python -m pytest pandas/tests/groupby pandas/tests/reshape pandas/tests/window "
               "pandas/tests/io/pytables -q -p no:cacheprovider -n 8 > /tmp/wide_tests.log 2>&1; echo EXIT $? >> "
               "/tmp/wide_tests.log) &\necho started")
    kinds = [k for k, _, _ in _summary(command)]
    assert kinds == ["test", "write_outside", "other"]
    # pilot-haiku-1, pandas 70742, tool, turn 14: git checkout reverts a file.
    assert _summary("git checkout pandas/core/internals/managers.py && sed -n 1260,1275p pandas/core/indexing.py") \
        == [("revert", "git checkout", ["pandas/core/internals/managers.py"]),
            ("view", "sed -n", ["pandas/core/indexing.py"])]
    # vague-l0-1, playwright 42503, tool, turn 11: a backup in /tmp, a revert, a test, and the fix copied back.
    command = ("cp packages/playwright/src/mcp/test/browserBackend.ts /tmp/fixed.ts && git checkout -- "
               "packages/playwright/src/mcp/test/browserBackend.ts && timeout 300 npx playwright test "
               "tests/mcp/cli-test.spec.ts -g \"multiple browser contexts\" --reporter=line 2>&1 | grep -m3 "
               "\"already started\\\\|passed\\\\|failed\"; cp /tmp/fixed.ts packages/playwright/src/mcp/test/"
               "browserBackend.ts && git status --short")
    assert [k for k, _, _ in _summary(command)] == ["write_outside", "revert", "test", "filter", "edit", "git"]
    # vague2-l1-1, pandas 70742, tool, turn 20: git show HEAD:PATH > PATH puts the old version back.
    command = ("git status --short && cp pandas/core/indexing.py /tmp/indexing_fixed.py && git show "
               "HEAD:pandas/core/indexing.py > pandas/core/indexing.py && timeout 300 python -m pytest "
               "pandas/tests/indexing/test_loc.py -q -p no:cacheprovider -k temporary 2>&1 | tail -1")
    assert [k for k, _, _ in _summary(command)][:3] == ["git", "write_outside", "revert"]
    assert _one("git show HEAD:pandas/core/indexing.py > /tmp/orig.py").kind == "write_outside"
    # A write to a repo file stays an edit.
    assert _one("echo x >> pandas/a.py").kind == "edit"
    # In a run: the revert of the gold file and the scratch files are not edits; the later edit is.
    events = _stream([_bash("cat > /tmp/repro.py <<'EOF'\nprint(1)\nEOF\npython /tmp/repro.py")],
                     [_bash("git checkout -- pandas/core/indexing.py", "Updated 1 path from the index")],
                     [_bash("cat >> pandas/core/indexing.py <<'EOF'\n# x\nEOF")])
    steps = count_steps(events, GOLD)
    assert steps["first_edit_turn"] == 3 and steps["gold"][GOLD[0]]["edited"] == 3
    assert (steps["edits"]["shell"], steps["edits"]["outside"], steps["edits"]["reverts"]) == (1, 1, 1)
    assert steps["actions"]["edit"] == 1 and steps["edits"]["files_edited"] == ["pandas/core/indexing.py"]


# ---- recount and score

def _old_record(run_id: str, task_id: str, *, gold: bool = True) -> tuple:
    out = e2e_run.run_dir(run_id, task_id, "grep", 1)
    out.mkdir(parents=True)
    (out / "stream.jsonl").write_text(FIXTURE_70742.read_text())
    identity = {"prompt_level": "L0", "machine": {"hostname": "höst"}}
    if gold:
        identity["gold_files"] = GOLD_70742
    record = {"schema": 1, "task_id": task_id, "setup": "grep", "rep": 1, "identity": identity,
              "time": {"agent_s": 61.25}, "result_event": {"num_turns": 18},
              "steps": {"turns": 17, "turns_before_first_edit": 6, "files_read": ["pandas/core/indexing.py"],
                        "gold_file_read": True, "first_gold_read_turn": 8, "num_turns_result": 18},
              "outcome": {"completed": True}}
    write_json(out / "run.json", record)
    return out / "run.json", record


def test_recount_changes_only_steps(tmp_path, capsys):
    path, record = _old_record("rc1", "pandas-dev__pandas-70742")
    before = path.read_text()
    assert main(["e2e", "recount", "rc1"]) == 0
    out = capsys.readouterr().out
    assert ("pandas-dev__pandas-70742 grep rep 1: content searches - -> 8, files viewed 1 -> 3, gold opened True "
            "-> True, first edit turn 7 -> 7") in out
    new = json.loads(path.read_text())
    assert new["steps"]["steps_version"] == e2e_steps.STEPS_VERSION and new["steps"]["first_gold_read_turn"] == 2
    assert new["steps"]["num_turns_result"] == 18
    # Everything but steps is the same, byte for byte.
    assert json.dumps({**new, "steps": record["steps"]}, indent=2, ensure_ascii=False) + "\n" == before


def test_recount_takes_gold_files_from_the_task_file(make_task, tmp_path, capsys):
    from cmeval.tasks import Gold, save_tasks
    path, _ = _old_record("rc2", "acme__auth-42", gold=False)
    assert main(["e2e", "recount", "rc2"]) == 0
    assert "no gold files in the record" in capsys.readouterr().out
    assert "steps_version" not in json.loads(path.read_text())["steps"]
    tasks = tmp_path / "tasks.jsonl"
    save_tasks(tasks, [make_task(gold=Gold(files=GOLD_70742))])
    assert main(["e2e", "recount", "rc2", "--tasks", str(tasks)]) == 0
    assert json.loads(path.read_text())["steps"]["gold_opened"]
    assert main(["e2e", "recount", "none"]) == 1


def _scored(run_id, task_id, setup, steps):
    out = e2e_run.run_dir(run_id, task_id, setup, 1)
    out.mkdir(parents=True)
    write_json(out / "run.json", {"task_id": task_id, "setup": setup, "rep": 1, "end": "finished", "completed": True,
                                  "discard": False, "flags": [], "tokens": {"processed_tokens": 10},
                                  "time": {"agent_s": 1.0}, "steps": steps})


def test_score_behaviour_table():
    steps = count_steps(e2e_steps.parse_stream(FIXTURE_70742)["events"], GOLD_70742)
    _scored("sb1", "t1", "grep", steps)
    _scored("sb1", "t2", "grep", {"turns": 9, "turns_before_first_edit": 2, "gold_file_read": False})  # version 1
    behaviour = score("sb1")["setups"]["grep"]["behaviour"]
    assert behaviour["content_searches_mean"] == 8 and behaviour["files_viewed_mean"] == 3
    assert behaviour["gold_opened_share"] == 0.5 and behaviour["first_gold_open_mean"] == 2
    assert behaviour["turns_before_first_edit_mean"] == 4 and behaviour["codemem_share"] == 0.0
    text = format_score(score("sb1"))
    assert "behaviour (means over kept runs)" in text and "codemem" not in text
    _scored("sb1", "t1", "tool", {**steps, "codemem_calls": 3})
    text = format_score(score("sb1"))
    assert "codemem" in text and score("sb1")["setups"]["tool"]["behaviour"]["codemem_share"] == 1.0
