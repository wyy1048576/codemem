"""The table of one run, one row per turn (cmeval e2e turns).

The fixtures in fixtures/e2e_turns/ are two real runs of claude-haiku-5-5 on playwright 42503: setup grep of
run pilot-haiku-1 (8 turns) and setup tool of run vague-l1-1 (9 turns, one codemem call). They were made small
from the full run folders: the stream as for the streams of test_e2e_steps (no thinking blocks, no copies of tool
results, each tool result cut to 2,000 characters, a short init event), the proxy log with only the fields the
table reads, and run.json with only the run's names, gold files, token totals and turns. The table of each fixture
is the same as the table of its full folder.
"""

import json
import shutil

import pytest

from cmeval import e2e_steps, e2e_turns
from cmeval.cli import main
from cmeval.e2e_turns import TurnsError, build_table, format_pair, format_table, match_requests, run_folder
from cmeval.paths import e2e_dir

from conftest import FIXTURES

TASK = "microsoft__playwright-42503"
GOLD = "packages/playwright/src/mcp/test/browserBackend.ts"
GREP = FIXTURES / "e2e_turns" / "pilot-haiku-1" / TASK / "grep" / "1"
TOOL = FIXTURES / "e2e_turns" / "vague-l1-1" / TASK / "tool" / "1"


@pytest.fixture
def runs():
    """The fixture runs in CMEVAL_HOME/e2e/runs."""
    root = e2e_dir() / "runs"
    shutil.copytree(FIXTURES / "e2e_turns", root)
    return root


def test_rows_of_the_grep_run():
    table = build_table(GREP)
    assert table["match"] == {"how": "message id", "turns": 8, "requests": 8, "turns_without_request": 0,
                              "other_requests": 0}
    rows = table["rows"]
    assert [r["turn"] for r in rows] == list(range(1, 9))
    first = rows[0]
    assert (first["start_s"], first["turn_s"], first["model_s"]) == (1.0, 2.0, 1.4)
    assert (first["input"], first["output"], first["cache_read"], first["cache_write"]) == (2, 146, 34179, 2201)
    assert first["tools"] == "Bash" and first["command"].startswith("git status | head -5 && ls && grep -rn")
    assert first["kinds"] == "git, filter x3, search_files, search_content"
    # The marks agree with count_steps of the same stream: surfaced 1, opened 4, edited 6.
    marks = [(r["turn"], r["surfaced"], r["opened"], r["edited"]) for r in rows if r["surfaced"] or r["opened"]]
    assert marks == [(1, "first", "", ""), (3, "yes", "", ""), (4, "yes", "first", ""), (5, "yes", "", ""),
                     (6, "yes", "yes", "first")]
    assert rows[5]["edited_files"] == [GOLD] and rows[5]["kinds"].startswith("edit_script")
    # The last turn has no tool call; its turn lasts to the end of the agent (clock.txt).
    assert rows[-1]["tools"] == "(text)" and rows[-1]["command"] == "" and rows[-1]["turn_s"] == 2.6
    # Each turn lasts until the next request.
    for row, nxt in zip(rows, rows[1:]):
        assert row["turn_s"] == pytest.approx(nxt["start_s"] - row["start_s"], abs=0.11)


def test_sums_equal_the_totals_of_run_json():
    for folder in (GREP, TOOL):
        table = build_table(folder)
        record = json.loads((folder / "run.json").read_text())
        sums, proxy = table["sums"], record["tokens"]["proxy"]
        assert (sums["input"], sums["output"], sums["cache_read"], sums["cache_write"]) == (
            proxy["input_tokens"], proxy["output_tokens"], proxy["cache_read_input_tokens"],
            proxy["cache_creation_input_tokens"])
        assert sums["processed_tokens"] == proxy["processed_tokens"] == record["tokens"]["processed_tokens"]
        assert sums["turns"] == record["steps"]["turns"]
        assert table["check"] == {"equal": True, "differ": [], "source": "proxy", "note": ""}


def test_codemem_call_shows_its_query():
    row = build_table(TOOL)["rows"][0]
    assert row["tools"] == "codemem.search_code, Bash"
    assert row["calls"][0]["label"].startswith("debug mode expose browser to playwright cli")
    assert row["calls"][0]["kinds"] == ["mcp"]
    assert row["command"].startswith("[1] debug mode") and " [2] git status --short" in row["command"]
    # With a narrow column each call keeps a part.
    cell = e2e_turns.command_cell(row, 60)
    assert cell.startswith("[1] debug mode") and "[2] git status" in cell and len(cell) <= 70


def test_turns_agree_with_count_steps():
    events = e2e_steps.parse_stream(TOOL / "stream.jsonl")["events"]
    steps = e2e_steps.count_steps(events, [GOLD])
    turns = e2e_steps.turn_steps(events, [GOLD])
    assert len(turns) == steps["turns"]
    assert sum(len(t["calls"]) for t in turns) == sum(steps["tool_calls"].values())
    for key in ("surfaced", "opened", "edited"):
        first = next((t["turn"] for t in turns if GOLD in t[key]), None)
        assert first == steps["gold"][GOLD][key]


def test_match_by_order_and_unmatched_requests(tmp_path):
    folder = tmp_path / "run"
    shutil.copytree(GREP, folder)
    lines = [json.loads(line) for line in (folder / "proxy.jsonl").read_text().splitlines()]
    # Without message ids the turns and requests match in order, when their counts are equal.
    (folder / "proxy.jsonl").write_text("".join(json.dumps({k: v for k, v in r.items() if k != "message_id"}) + "\n"
                                                for r in lines))
    table = build_table(folder)
    assert table["match"]["how"] == "order" and table["check"]["equal"]
    assert table["rows"][0]["input"] == 2 and table["rows"][0]["output"] == 146
    # A request that no turn has (a subagent's) goes to the row of other requests, and the sums still hold.
    extra = dict(lines[2], seq=99, message_id="msg_subagent", usage={"input_tokens": 5, "output_tokens": 7})
    (folder / "proxy.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines + [extra]))
    table = build_table(folder)
    assert table["match"]["other_requests"] == 1
    assert table["other_requests"] == {"input": 5, "output": 7, "cache_read": 0, "cache_write": 0, "requests": 1}
    assert not table["check"]["equal"] and "input_tokens" in table["check"]["differ"]
    # Without message ids and with other counts, no turn gets a request.
    turns = [{"message_id": "a"}, {"message_id": "b"}]
    assert match_requests(turns, [{"seq": 1}]) == ([None, None], "none")


def test_formats():
    table = build_table(GREP)
    md = format_table(table, "md", width=40)
    lines = md.splitlines()
    assert lines[0].startswith(f"run pilot-haiku-1, task {TASK}, setup grep, rep 1: claude-haiku-5-5")
    assert "| turn | start_s | turn_s | model_s | input | output | cache_read | cache_write | tools |" in md
    assert "git status \\| head -5" in md  # a pipe in a command does not break the table
    assert all(len(cell) <= 42 for line in lines if line.startswith("| ") for cell in line.split(" | ")[9:10])
    assert "| sum |  | 35.6 | 19.4 | 16 | 2821 | 326769 | 13489 | 7 calls | processed 343095 |  | 5 | 2 | 1 |" in md
    assert lines[-1] == "check: the sums equal the totals of run.json"
    csv_lines = format_table(table, "csv").splitlines()
    assert csv_lines[0] == ",".join(e2e_turns.COLUMNS) and csv_lines[-1].startswith("sum,")
    assert len(csv_lines) == 1 + 8 + 2
    assert json.loads(format_table(table, "json"))["sums"]["processed_tokens"] == 343095


def test_side_by_side():
    text = format_pair(build_table(GREP), build_table(TOOL), "md", width=30)
    lines = text.splitlines()
    assert lines[0] == "A: pilot-haiku-1/grep/1 (finished, completed False)"
    assert lines[1] == "B: vague-l1-1/tool/1 (finished, completed False)"
    assert "| 1 | 1.0 | 36528 | Bash |" in text
    assert "| 9 |  |  |  |  |  | " in text  # the grep run has 8 turns, the tool run 9
    assert "| S O E* |" in text  # turn 6 of the grep run: shown, opened, and the first edit
    assert lines[-2:] == ["A check: the sums equal the totals of run.json",
                          "B check: the sums equal the totals of run.json"]


def test_run_folder(runs):
    assert run_folder("pilot-haiku-1", TASK) == runs / "pilot-haiku-1" / TASK / "grep" / "1"
    assert run_folder(str(runs / "vague-l1-1"), TASK, "tool") == runs / "vague-l1-1" / TASK / "tool" / "1"
    (runs / "pilot-haiku-1" / TASK / "tool").mkdir()
    with pytest.raises(TurnsError, match="setups grep, tool; give --setup"):
        run_folder("pilot-haiku-1", TASK)
    with pytest.raises(TurnsError, match="no folder"):
        run_folder("pilot-haiku-1", TASK, "grep", rep=2)
    with pytest.raises(TurnsError, match="no folder"):
        run_folder("nope", TASK)
    aside = runs / "pilot-haiku-1" / TASK / "grep" / "1.discarded-1"
    aside.mkdir()
    assert run_folder("pilot-haiku-1", TASK, "grep", rep="1.discarded-1") == aside


def test_cli_turns(runs, capsys):
    assert main(["e2e", "turns", "pilot-haiku-1", "--id", TASK]) == 0
    out = capsys.readouterr().out
    assert out.startswith("run pilot-haiku-1") and out.endswith("check: the sums equal the totals of run.json\n")
    assert main(["e2e", "turns", "pilot-haiku-1", "--id", TASK, "--with", "vague-l1-1", "--format", "csv"]) == 0
    header = capsys.readouterr().out.splitlines()[0]
    assert header.startswith("turn,A start_s,A processed,A tools,A command,A gold,B start_s")
    (runs / "pilot-haiku-1" / TASK / "tool").mkdir()
    assert main(["e2e", "turns", "pilot-haiku-1", "--id", TASK]) == 1
    assert "give --setup" in capsys.readouterr().err
    # Two setups of one run id, side by side.
    shutil.copytree(TOOL, runs / "pilot-haiku-1" / TASK / "tool" / "1")
    assert main(["e2e", "turns", "pilot-haiku-1", "--id", TASK, "--setup", "grep", "--setup", "tool"]) == 0
    assert capsys.readouterr().out.startswith("A: pilot-haiku-1/grep/1")
    # A run.json without gold files needs the task file.
    record = json.loads((runs / "vague-l1-1" / TASK / "tool" / "1" / "run.json").read_text())
    del record["identity"]
    (runs / "vague-l1-1" / TASK / "tool" / "1" / "run.json").write_text(json.dumps(record))
    assert main(["e2e", "turns", "vague-l1-1", "--id", TASK]) == 1
    assert "give the task file with --tasks" in capsys.readouterr().err


def test_cli_turns_gold_from_the_task_file(runs, make_task, tmp_path, capsys):
    from dataclasses import replace

    from cmeval.tasks import save_tasks

    task = make_task()
    task = replace(task, id=TASK, repo="microsoft/playwright", fix=replace(task.fix, pr_number=42503))
    path = tmp_path / "tasks.jsonl"
    save_tasks(path, [task])
    # The task file's gold files win: auth/sessions.py is never shown, so no turn has a mark.
    assert main(["e2e", "turns", "vague-l1-1", "--id", TASK, "--tasks", str(path), "--format", "json"]) == 0
    table = json.loads(capsys.readouterr().out)
    assert table["gold_files"] == ["auth/sessions.py"] and table["sums"]["surfaced"] == 0
    assert main(["e2e", "turns", "vague-l1-1", "--id", "acme__auth-7", "--tasks", str(path)]) == 1
    assert "no task acme__auth-7" in capsys.readouterr().err
