"""Incremental updates must equal a fresh build, after any sequence of edits.

Each test edits a copy of the sample repo step by step. After every step the index is updated,
either through the changed paths (what the watcher reports) or by a scan of the whole repo, and
compared with a fresh build of the same files (`Indexer.verify()`). A difference fails the test
with the list of differing records.
"""

import os
import random
import shutil
from pathlib import Path

import pytest

from codemem.indexer import Indexer
from codemem.store import Store

SAMPLE = Path(__file__).parent / "fixtures" / "sample_repo"
MODES = ("paths", "scan")


class Repo:
    """A copy of the sample repo with an index that is updated after each edit."""

    def __init__(self, tmp_path, config, mode):
        self.root = tmp_path / "repo"
        shutil.copytree(SAMPLE, self.root)
        self.config = config
        self.store = Store(tmp_path / "idx")
        self.indexer = Indexer(self.root, self.store, config)
        self.mode = mode
        self.touched: set[str] = set()
        self.indexer.update()

    def read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def has(self, rel, text=None):
        p = self.root / rel
        return p.is_file() and (text is None or text in p.read_text(encoding="utf-8"))

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        self.touched.add(rel)

    def replace(self, rel, old, new):
        text = self.read(rel)
        assert old in text, (rel, old)
        self.write(rel, text.replace(old, new, 1))

    def delete(self, rel):
        (self.root / rel).unlink()
        self.touched.add(rel)

    def move(self, src, dst):
        (self.root / dst).parent.mkdir(parents=True, exist_ok=True)
        os.rename(self.root / src, self.root / dst)
        self.touched |= {src, dst}

    def sync(self):
        if self.mode == "scan" or ".gitignore" in self.touched:
            self.indexer.reset_rules()  # the watcher does this for an ignore-rule change
            stats = self.indexer.update()
        else:
            stats = self.indexer.update(paths=sorted(self.touched))
        self.touched.clear()
        return stats

    def check(self):
        diff = self.indexer.verify()
        assert diff == [], "\n".join(diff)

    def step(self, edit):
        edit(self)
        self.sync()
        self.check()


# --------------------------------------------------------------------------- edits
# Each edit returns False when it does not apply to the repo's current state.


def body_edit(r):
    if not r.has("auth/sessions.py", "db.sessions.delete(session_id)\n"):
        return False
    r.replace("auth/sessions.py", "db.sessions.delete(session_id)\n", "db.sessions.delete(session_id)\n    db.log(session_id)\n")


def rename_definition_only(r):
    if not r.has("auth/sessions.py", "def revoke_session("):
        return False
    r.replace("auth/sessions.py", "def revoke_session(", "def end_session(")


def rename_everywhere(r):
    files = [f for f in ("auth/sessions.py", "api/routes.py", "auth/users.py", "tests/test_users.py") if r.has(f)]
    if not any(r.has(f, "revoke_session") for f in files):
        return False
    for f in files:
        if r.has(f, "revoke_session"):
            r.write(f, r.read(f).replace("revoke_session", "end_session"))


def add_caller(r):
    if not r.has("api/routes.py") or r.has("api/routes.py", "def kick("):
        return False
    r.write("api/routes.py", r.read("api/routes.py") + "\n\ndef kick(request):\n    revoke_session(request.token)\n    disable_user(request.user)\n")


def remove_caller(r):
    if not r.has("api/routes.py", "    revoke_session(request.token)\n    return"):
        return False
    r.replace("api/routes.py", "    revoke_session(request.token)\n    return", "    return")


def move_function(r):
    if not r.has("auth/sessions.py", "def new_token():"):
        return False
    text = r.read("auth/sessions.py")
    func = "def new_token():\n    return secrets.token_hex(16)\n"
    assert func in text
    r.write("auth/sessions.py", text.replace(func, ""))
    r.write("auth/tokens.py", "import secrets\n\n\n" + func)


def delete_file(r):
    if not r.has("api/routes.py"):
        return False
    r.delete("api/routes.py")


def add_file(r):
    if r.has("api/health.py"):
        return False
    r.write("api/health.py", "def healthcheck():\n    return check_db()\n\n\ndef check_db():\n    return db.users.find()\n")


def crowd_a_name(r):
    """Five more `delete` definitions: the name passes max_defs_per_name, so its links go away."""
    if r.has("extra/m1.py"):
        return False
    for i in range(1, 6):
        r.write(f"extra/m{i}.py", f"class Store{i}:\n    def delete(self, key):\n        return key\n")


def uncrowd_a_name(r):
    if not r.has("extra/m5.py"):
        return False
    r.delete("extra/m5.py")


def comment_edit(r):
    if not r.has("auth/users.py", "def get_user_by_id("):
        return False
    if r.has("auth/users.py", "# Look a user up.\n"):
        r.replace("auth/users.py", "# Look a user up.\n", "# Look a user up by id; None if missing.\n")
    else:
        r.replace("auth/users.py", "def get_user_by_id(", "# Look a user up.\ndef get_user_by_id(")


def duplicate_names(r):
    """Two `helper`s with nested `inner`s; renaming the first renumbers the second's keys."""
    src = "def {a}():\n    def inner():\n        return 1\n    return inner()\n\n\ndef helper():\n    def inner():\n        return 2\n    return inner()\n"
    if not r.has("auth/dup.py"):
        r.write("auth/dup.py", src.format(a="helper"))
    elif r.has("auth/dup.py", "def helper():\n    def inner():\n        return 1"):
        r.write("auth/dup.py", src.format(a="helper_a"))
    else:
        return False


def ignore_a_file(r):
    if r.has(".gitignore", "auth/db.py"):
        r.replace(".gitignore", "auth/db.py\n", "")
    else:
        r.write(".gitignore", r.read(".gitignore") + "auth/db.py\n")


def generated_marker(r):
    if r.has("auth/users.py", "# @generated\n"):
        r.replace("auth/users.py", "# @generated\n", "")
    elif r.has("auth/users.py"):
        r.write("auth/users.py", "# @generated\n" + r.read("auth/users.py"))
    else:
        return False


def header_flips_c_to_cpp(r):
    c = "struct session { int id; };\n\nint revoke(struct session *s) {\n    return drop(s->id);\n}\n"
    if not r.has("native/session.h"):
        r.write("native/session.h", c)
    elif not r.has("native/session.h", "namespace"):
        r.write("native/session.h", "namespace auth { int helper(); }\n\n" + c)
    else:
        return False


def touch_only(r):
    p = r.root / "auth" / "sessions.py"
    if not p.exists():
        return False
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 5))
    r.touched.add("auth/sessions.py")


def huge_statement(r):
    rows = "\n".join(f'    "K{i}": lambda: getenv("K{i}"),' for i in range(260))
    if not r.has("auth/envs.py"):
        r.write("auth/envs.py", f"ENV = {{\n{rows}\n}}\n")
    elif not r.has("auth/envs.py", '"NEW"'):
        r.replace("auth/envs.py", '    "K3"', '    "NEW": lambda: None,\n    "K3"')
    else:
        return False


EDITS = [
    body_edit, rename_definition_only, rename_everywhere, add_caller, remove_caller, move_function, delete_file,
    add_file, crowd_a_name, uncrowd_a_name, comment_edit, duplicate_names, ignore_a_file, generated_marker,
    header_flips_c_to_cpp, touch_only, huge_statement,
]


# --------------------------------------------------------------------------- tests


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("edit", EDITS, ids=lambda e: e.__name__)
def test_each_edit_matches_a_fresh_build(tmp_path, fake_config, mode, edit):
    r = Repo(tmp_path, fake_config, mode)
    r.check()
    for _ in range(2):  # apply, then apply again where the edit toggles or continues
        if edit(r) is False:
            break
        r.sync()
        r.check()


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("seed", range(4))
def test_random_edit_scripts_match_a_fresh_build(tmp_path, fake_config, mode, seed):
    rng = random.Random(seed)
    r = Repo(tmp_path, fake_config, mode)
    done = 0
    while done < 10:
        edit = rng.choice(EDITS)
        if edit(r) is False:
            continue
        r.sync()
        r.check()
        done += 1


def test_case_only_rename(tmp_path, fake_config):
    r = Repo(tmp_path, fake_config, "paths")
    r.move("auth/users.py", "auth/tmp_users.py")  # via a temp name: works on case-insensitive disks too
    r.move("auth/tmp_users.py", "auth/Users.py")
    r.touched.discard("auth/tmp_users.py")
    r.sync()
    r.check()
    assert r.store.get_chunk_by_key("auth/users.py::disable_user") is None
    assert r.store.get_chunk_by_key("auth/Users.py::disable_user") is not None


def test_folder_move_is_seen_from_the_folder_path_alone(tmp_path, fake_config):
    r = Repo(tmp_path, fake_config, "paths")
    os.rename(r.root / "api", r.root / "web")
    r.touched |= {"api", "web"}  # the watcher reports the folder, not each file
    r.sync()
    r.check()
    assert r.store.get_chunk_by_key("web/routes.py::logout") is not None


@pytest.mark.parametrize(
    "setting, value",
    [("code_header", False), ("max_defs_per_name", 1), ("embedding_dim", 32), ("max_block_lines", 3)],
)
def test_a_settings_change_reaches_unchanged_files(tmp_path, fake_config, setting, value):
    r = Repo(tmp_path, fake_config, "scan")
    setattr(fake_config, setting, value)
    r.sync()  # no file changed
    r.check()


def test_a_model_change_re_embeds_only_that_vector_type(tmp_path, fake_config):
    r = Repo(tmp_path, fake_config, "scan")
    n_code = len(r.store.vector_rows("code"))
    fake_config.vectors["code"].model = "fake:32"
    stats = r.sync()
    assert stats.embedded["code"] == n_code and stats.embedded["usage"] == 0
    r.check()


def test_the_queue_survives_a_crash_between_the_two_stages(tmp_path, fake_config):
    from codemem.indexer import IndexStats

    r = Repo(tmp_path, fake_config, "paths")
    body_edit(r)
    r.indexer.structure(IndexStats(), paths=sorted(r.touched))  # stage A committed, then "crash"
    r.touched.clear()
    assert r.store.dirty_count() > 0
    r.store.close()

    store = Store(tmp_path / "idx")
    stats = Indexer(r.root, store, fake_config).update()  # a restart: nothing changed on disk
    assert stats.embedded["code"] >= 1 and store.dirty_count() == 0
    assert Indexer(r.root, store, fake_config).verify() == []
    store.close()
