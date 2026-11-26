"""Call and import links around the gold functions of the tasks codemem missed in its top 50.

Reads task commits from bare repos, with no checkout. Uses codemem's own file selection, chunker and
call names, so its chunks line up with the hits of an eval run. Writes, for each gold function, the
chunks it calls or is called by, and the files its file imports or is imported by.

Two kinds of call link:
- name:   codemem's rule today. A call links to every definition of that name in the language
          family, unless the name has more than max_defs_per_name definitions.
- scoped: a call links to a definition of that name only in the caller's own file, or a file it
          directly imports (C/C++: also the header or source partner of those files).

Usage: python build_links.py TASK_ROWS.json REPOS_DIR TASKS_DIR OUT_DIR [--workers N]
       python build_links.py --selftest
"""
from __future__ import annotations

import argparse
import collections as C
import gzip
import json
import logging
import os
import posixpath as pp
import re
import sqlite3
import subprocess
import sys
import threading
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pathspec
from codemem.chunker import chunk_source
from codemem.config import ALWAYS_SKIP_DIRS, DEFAULT_IGNORE, config_from_dict
from codemem.indexer import indexed_extensions, skip_reason
from codemem.languages import get_language, language_for_path
from codemem.schema import CALLABLE_KINDS

CFG = config_from_dict({})
EXTS = indexed_extensions(CFG)
PARSE_VERSION = "1"
GOLD_FILES = False
PY_DESCEND = frozenset({
    "module", "block", "if_statement", "elif_clause", "else_clause", "try_statement", "except_clause",
    "except_group_clause", "finally_clause", "with_statement", "for_statement", "while_statement",
    "function_definition", "class_definition", "decorated_definition", "match_statement", "case_clause",
})
JS_LANGS = frozenset({"javascript", "typescript", "tsx"})
C_LANGS = frozenset({"c", "cpp"})
JS_CALL = re.compile(rb"""(?:\brequire|\bimport)\s*\(\s*['"]([^'"\n]+)['"]\s*\)""")
C_INCLUDE = re.compile(rb"""^[ \t]*#[ \t]*include[ \t]*([<"])([^>"\n]+)[>"]""", re.M)
TS_EXTS = (".ts", ".tsx", ".d.ts", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
JS_SUFFIX = re.compile(r"\.(?:js|jsx|mjs|cjs)$")
C_SOURCE = (".c", ".cc", ".cpp", ".cxx", ".cu", ".c++")
C_HEADER = (".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".ipp")


# ---- reading git


def git_tree(repo: Path, sha: str):
    out = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-l", "-z", sha], capture_output=True, check=True).stdout
    for record in out.split(b"\0"):
        if record:
            meta, path = record.split(b"\t", 1)
            mode, kind, oid, size = meta.split()
            yield mode.decode(), kind.decode(), oid.decode(), 0 if size == b"-" else int(size), path.decode("utf-8", "replace")


def read_blobs(repo: Path, oids: list[str]):
    proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def feed():
        for oid in oids:
            proc.stdin.write(oid.encode() + b"\n")
        proc.stdin.close()

    threading.Thread(target=feed, daemon=True).start()
    for oid in oids:
        header = proc.stdout.readline().split()
        if len(header) < 3:
            continue
        data = proc.stdout.read(int(header[2]))
        proc.stdout.read(1)
        yield oid, data
    proc.wait()


class BlobIgnore:
    """codemem's IgnoreRules, reading .gitignore files from a git tree instead of the disk."""

    def __init__(self, gitignores: dict[str, str]):
        extra = [*CFG.ignore, *(DEFAULT_IGNORE if CFG.use_default_ignore else ())]
        self.specs: dict[str, pathspec.PathSpec] = {"": pathspec.GitIgnoreSpec.from_lines(extra)}
        for base, text in gitignores.items():
            spec = pathspec.GitIgnoreSpec.from_lines(text.splitlines())
            self.specs[base] = self.specs[base] + spec if base in self.specs else spec
        self.dirs: dict[str, bool] = {}

    def ignored(self, rel: str, is_dir: bool) -> bool:
        for base, spec in self.specs.items():
            if base and not rel.startswith(base + "/"):
                continue
            sub = rel[len(base) + 1:] if base else rel
            if spec.match_file(sub + "/" if is_dir else sub):
                return True
        return False

    def dir_ok(self, rel: str) -> bool:
        if not rel:
            return True
        if rel not in self.dirs:
            parent, name = pp.split(rel)
            self.dirs[rel] = self.dir_ok(parent) and name not in ALWAYS_SKIP_DIRS and not self.ignored(rel, True)
        return self.dirs[rel]

    def allows(self, rel: str) -> bool:
        return self.dir_ok(pp.dirname(rel)) and not self.ignored(rel, False)


# ---- parsing one file (runs in worker processes)


def python_imports(root) -> list:
    found = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "import_statement":
            for name in node.children_by_field_name("name"):
                target = name.child_by_field_name("name") if name.type == "aliased_import" else name
                found.append([0, target.text.decode("utf-8", "replace"), []])
        elif node.type == "import_from_statement":
            module = node.child_by_field_name("module_name")
            if module is None:
                continue
            level, text = 0, module.text.decode("utf-8", "replace")
            if module.type == "relative_import":
                prefix = next((c for c in module.children if c.type == "import_prefix"), None)
                level = len(prefix.text) if prefix is not None else 1
                dotted = next((c for c in module.children if c.type == "dotted_name"), None)
                text = dotted.text.decode("utf-8", "replace") if dotted is not None else ""
            names = []
            for name in node.children_by_field_name("name"):
                target = name.child_by_field_name("name") if name.type == "aliased_import" else name
                names.append(target.text.decode("utf-8", "replace"))
            found.append([level, text, names])
        elif node.type in PY_DESCEND:
            stack.extend(node.named_children)
    return found


def js_imports(root, data: bytes) -> list:
    specs = []
    for node in root.named_children:
        if node.type in ("import_statement", "export_statement"):
            source = node.child_by_field_name("source")
            if source is not None:
                fragment = next((c for c in source.named_children if c.type == "string_fragment"), None)
                if fragment is not None:
                    specs.append(fragment.text.decode("utf-8", "replace"))
    specs += [m.decode("utf-8", "replace") for m in JS_CALL.findall(data)]
    return list(dict.fromkeys(specs))


def parse_one(item):
    key, path, data = item
    logging.disable(logging.WARNING)
    try:
        language = language_for_path(path, data)
        if language is None:
            return key, {"skip": "language"}
        why = skip_reason(data, language, CFG)
        if why:
            return key, {"skip": why}
        chunks = chunk_source(data, path, language, max_block_lines=CFG.max_block_lines)
        imports: list = []
        if language == "python":
            imports = python_imports(get_language(language).parser().parse(data).root_node)
        elif language in JS_LANGS:
            imports = js_imports(get_language(language).parser().parse(data).root_node, data)
        elif language in C_LANGS:
            imports = [[q.decode(), s.decode("utf-8", "replace").strip()] for q, s in C_INCLUDE.findall(data)]
        return key, {"language": language, "family": get_language(language).family, "imports": imports,
                     "chunks": [[c.key, c.kind, c.name, c.qualname, c.start_line, c.end_line, c.calls, int(c.is_test)] for c in chunks]}
    except Exception as exc:  # recorded, so a failed file is counted and never silently absent
        return key, {"skip": f"error:{type(exc).__name__}"}


# ---- resolving imports to files


def strip_jsonc(text: str) -> str:
    out, i, n, in_string = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        else:
            out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def common_dirs(a: str, b: str) -> int:
    count = 0
    for x, y in zip(a.split("/")[:-1], b.split("/")[:-1]):
        if x != y:
            break
        count += 1
    return count


def closest(importer: str, candidates) -> str | None:
    best, best_key = None, None
    for candidate in candidates:
        key = (-common_dirs(importer, candidate), candidate.count("/"), candidate)
        if best_key is None or key < best_key:
            best, best_key = candidate, key
    return best


class Resolver:
    def __init__(self, files: set[str], tsconfigs: dict[str, str] | None = None, packages: dict[str, str] | None = None):
        self.files = files
        self.by_base: dict[str, list[str]] = C.defaultdict(list)
        for f in files:
            self.by_base[pp.basename(f)].append(f)
        self._index_python()
        self._index_ts(tsconfigs or {}, packages or {})

    def _index_python(self):
        py = [f for f in self.files if f.endswith((".py", ".pyi"))]
        init_dirs = {pp.dirname(f) for f in py if pp.basename(f) in ("__init__.py", "__init__.pyi")}
        roots = {""}
        for d in init_dirs:
            while d in init_dirs:
                d = pp.dirname(d)
            roots.add(d)
        for f in py:
            d = pp.dirname(f)
            while d:
                if pp.basename(d) == "src":
                    roots.add(d)
                d = pp.dirname(d)
        self.py_index: dict[str, list[tuple[str, str]]] = C.defaultdict(list)
        for f in py:
            stem = f.rsplit(".", 1)[0]
            d = pp.dirname(f)
            while True:
                if d in roots:
                    rel = stem[len(d) + 1:] if d else stem
                    if rel.endswith("/__init__"):
                        rel = rel[:-len("/__init__")]
                    if rel != "__init__" and all(part.isidentifier() for part in rel.split("/")):
                        self.py_index[rel.replace("/", ".")].append((f, d))
                if not d:
                    break
                d = pp.dirname(d)

    def _py_package(self, path: str) -> str | None:
        for candidate in (f"{path}.py", f"{path}.pyi", pp.join(path, "__init__.py"), pp.join(path, "__init__.pyi")):
            if candidate in self.files:
                return candidate
        return None

    def _py_find(self, importer: str, dotted: str) -> str | None:
        candidates = self.py_index.get(dotted)
        if not candidates:
            return None
        if dotted.split(".")[0] in sys.stdlib_module_names:  # `import json` is not some nested json package
            candidates = [(f, r) for f, r in candidates if not r or importer.startswith(r + "/")]
        return closest(importer, [f for f, _ in candidates])

    def python(self, importer: str, level: int, module: str, names: list[str]) -> set[str]:
        out: set[str] = set()
        if level:
            base = pp.dirname(importer)
            for _ in range(level - 1):
                base = pp.dirname(base)
            path = pp.join(base, module.replace(".", "/")) if module else base
            found = self._py_package(path) if path else ("__init__.py" if "__init__.py" in self.files else None)
            for name in names:
                sub = self._py_package(pp.join(path, name))
                if sub:
                    out.add(sub)
                elif found:
                    out.add(found)
            if not names and found:
                out.add(found)
            return out
        found = self._py_find(importer, module)
        for name in names:
            sub = self._py_find(importer, f"{module}.{name}")
            if sub:
                out.add(sub)
            elif found:
                out.add(found)
        if not names and found:
            out.add(found)
        return out

    def _index_ts(self, tsconfigs: dict[str, str], packages: dict[str, str]):
        self.ts_maps: list[tuple[str, str, list[str]]] = []
        self.ts_bases: list[tuple[str, str]] = []
        for path, text in tsconfigs.items():
            try:
                options = json.loads(strip_jsonc(text)).get("compilerOptions") or {}
            except (ValueError, AttributeError):
                continue
            base_dir = pp.dirname(path)
            base = pp.normpath(pp.join(base_dir, options["baseUrl"])) if options.get("baseUrl") else base_dir
            base = "" if base == "." else base
            if options.get("baseUrl"):
                self.ts_bases.append((base_dir, base))
            for pattern, targets in (options.get("paths") or {}).items():
                self.ts_maps.append((base_dir, pattern, [pp.normpath(pp.join(base, t)) for t in targets]))
        self.ts_maps.sort(key=lambda m: -len(m[1]))
        self.packages: list[tuple[str, str, str]] = []
        for path, text in packages.items():
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                self.packages.append((data["name"], pp.dirname(path), str(data.get("main") or "")))
        self.packages.sort(key=lambda p: -len(p[0]))

    def _ts_file(self, path: str) -> str | None:
        path = pp.normpath(path)
        if path in self.files:
            return path
        if JS_SUFFIX.search(path):
            stem = JS_SUFFIX.sub("", path)
            for ext in (".ts", ".tsx", ".d.ts", ".mts", ".cts"):
                if stem + ext in self.files:
                    return stem + ext
        for ext in TS_EXTS:
            if path + ext in self.files:
                return path + ext
        for ext in TS_EXTS:
            if f"{path}/index{ext}" in self.files:
                return f"{path}/index{ext}"
        return None

    def typescript(self, importer: str, spec: str) -> set[str]:
        spec = spec.split("?", 1)[0]
        if spec.startswith("."):
            found = self._ts_file(pp.join(pp.dirname(importer), spec))
            return {found} if found else set()
        for _, pattern, targets in sorted(self.ts_maps, key=lambda m: (-common_dirs(importer, m[0] + "/x"), -len(m[1]))):
            if pattern.endswith("*"):
                if not spec.startswith(pattern[:-1]):
                    continue
                rest = spec[len(pattern) - 1:]
            elif spec == pattern:
                rest = ""
            else:
                continue
            for target in targets:
                found = self._ts_file(target.replace("*", rest))
                if found:
                    return {found}
        for config_dir, base in self.ts_bases:
            if not config_dir or importer.startswith(config_dir + "/"):
                found = self._ts_file(pp.join(base, spec))
                if found:
                    return {found}
        for name, directory, main in self.packages:
            if spec != name and not spec.startswith(name + "/"):
                continue
            rest = spec[len(name) + 1:]
            options = []
            if rest:
                options += [pp.join(directory, rest), pp.join(directory, "src", rest)]
                if rest.startswith("lib/"):
                    options.append(pp.join(directory, "src", rest[4:]))
            else:
                if main:
                    options += [pp.join(directory, main), pp.join(directory, re.sub(r"^(\./)?lib/", "src/", main))]
                options += [pp.join(directory, "src/index"), pp.join(directory, "index")]
            for option in options:
                found = self._ts_file(option)
                if found:
                    return {found}
        return set()

    def include(self, importer: str, quote: str, spec: str) -> set[str]:
        if quote == '"':
            local = pp.normpath(pp.join(pp.dirname(importer), spec))
            if local in self.files:
                return {local}
        tail = re.sub(r"^(\.\.?/)+", "", spec)
        if quote == "<" and "/" not in tail:
            return set()
        candidates = [f for f in self.by_base.get(pp.basename(tail), ()) if f == tail or f.endswith("/" + tail)]
        found = closest(importer, candidates)
        return {found} if found else set()


# ---- one commit


class ParseCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS parsed (k TEXT PRIMARY KEY, v BLOB NOT NULL)")
        self.memo: dict[str, dict] = {}

    def get_many(self, keys: list[str]) -> list[str]:
        missing = []
        unseen = [k for k in keys if k not in self.memo]
        for start in range(0, len(unseen), 500):
            batch = unseen[start:start + 500]
            found = dict(self.db.execute(f"SELECT k, v FROM parsed WHERE k IN ({','.join('?' * len(batch))})", batch))
            for key in batch:
                if key in found:
                    self.memo[key] = json.loads(zlib.decompress(found[key]))
                else:
                    missing.append(key)
        return missing

    def put(self, items: list[tuple[str, dict]]):
        self.db.executemany("INSERT OR REPLACE INTO parsed VALUES (?, ?)",
                            [(k, zlib.compress(json.dumps(v, separators=(",", ":")).encode("utf-8"))) for k, v in items])
        self.db.commit()
        self.memo.update(items)


def build_commit(repo_name, repo_dir, sha, gold, cache, pool, writer):
    start = time.time()
    entries = [e for e in git_tree(repo_dir, sha) if e[1] == "blob" and e[0] != "120000"]
    config_blobs = [(e[2], e[4]) for e in entries if pp.basename(e[4]) == ".gitignore" or re.fullmatch(r"[tj]sconfig[^/]*\.json", pp.basename(e[4]))
                    or (pp.basename(e[4]) == "package.json" and "node_modules/" not in e[4])]
    oids = list(dict.fromkeys(oid for oid, _ in config_blobs))
    texts = {oid: data.decode("utf-8", "replace") for oid, data in read_blobs(repo_dir, oids)}
    gitignores = {pp.dirname(p): texts.get(o, "") for o, p in config_blobs if pp.basename(p) == ".gitignore"}
    tsconfigs = {p: texts.get(o, "") for o, p in config_blobs if pp.basename(p).endswith(".json") and pp.basename(p) != "package.json"}
    packages = {p: texts.get(o, "") for o, p in config_blobs if pp.basename(p) == "package.json"}
    rules = BlobIgnore(gitignores)
    why_out: dict[str, str] = {}
    selected: dict[str, str] = {}
    for _mode, _kind, oid, size, path in entries:
        if os.path.splitext(path)[1].lower() not in EXTS:
            why_out[path] = "not a supported language"
        elif not rules.allows(path):
            why_out[path] = "ignored folder or pattern"
        elif size > CFG.max_file_size:
            why_out[path] = "too large"
        else:
            selected[path] = oid

    keys = {path: f"{PARSE_VERSION}|{oid}|{path}" for path, oid in selected.items()}
    missing = cache.get_many(list(keys.values()))
    if missing:
        wanted = C.defaultdict(list)
        for key in missing:
            _, oid, path = key.split("|", 2)
            wanted[oid].append((key, path))
        batch, size = [], 0

        def flush():
            nonlocal batch, size
            if batch:
                cache.put(list(pool.map(parse_one, batch, chunksize=8)))
                batch, size = [], 0

        for oid, data in read_blobs(repo_dir, list(wanted)):
            for key, path in wanted[oid]:
                batch.append((key, path, data))
                size += len(data)
            if len(batch) >= 400 or size > 64_000_000:
                flush()
        flush()

    records = {path: cache.memo.get(key, {"skip": "unread"}) for path, key in keys.items()}
    for path, record in records.items():
        if "skip" in record:
            why_out[path] = record["skip"]
    files = {p for p, r in records.items() if "chunks" in r}
    resolver = Resolver(files, tsconfigs, packages)

    out_edges: dict[str, set[str]] = C.defaultdict(set)
    in_edges: dict[str, set[str]] = C.defaultdict(set)
    stats = C.Counter()
    for path in files:
        record = records[path]
        language = record["language"]
        for item in record["imports"]:
            if language == "python":
                targets = resolver.python(path, *item)
                kind = "py_relative" if item[0] else "py_absolute"
            elif language in JS_LANGS:
                targets = resolver.typescript(path, item)
                kind = "js_relative" if item.startswith(".") else "js_package"
            else:
                targets = resolver.include(path, *item)
                kind = "c_quote" if item[0] == '"' else "c_angle"
            stats[kind] += 1
            stats[kind + "_resolved"] += bool(targets)
            for target in targets:
                if target != path:
                    out_edges[path].add(target)
                    in_edges[target].add(path)

    partners: dict[str, set[str]] = C.defaultdict(set)
    for path, targets in out_edges.items():
        if path.endswith(C_SOURCE):
            stem = pp.basename(path).rsplit(".", 1)[0]
            for target in targets:
                if target.endswith(C_HEADER) and pp.basename(target).rsplit(".", 1)[0] == stem:
                    partners[path].add(target)
                    partners[target].add(path)

    def scope(path):
        out = {path, *out_edges.get(path, ()), *partners.get(path, ())}
        for target in out_edges.get(path, ()):
            out |= partners.get(target, set())
        return out

    chunks, by_file, definitions = [], C.defaultdict(list), C.defaultdict(list)
    for path in files:
        record = records[path]
        for c in record["chunks"]:
            index = len(chunks)
            chunks.append((path, record["family"], *c))
            by_file[path].append(index)
            if c[1] in CALLABLE_KINDS:
                definitions[(record["family"], c[2])].append(index)
    gold_names = C.defaultdict(list)
    mapped = {}
    for task in gold:
        for g in task["gold"]["functions"]:
            best, best_iou = None, 0.0
            for index in by_file.get(g["path"], ()):
                c = chunks[index]
                if c[3] not in ("function", "method"):
                    continue
                inter = max(0, min(c[7], g["end"]) - max(c[6], g["start"]) + 1)
                union = max(c[7], g["end"]) - min(c[6], g["start"]) + 1
                if inter / union > best_iou:
                    best, best_iou = index, inter / union
            if best is not None and best_iou >= 0.5:
                mapped[(task["id"], g["path"], g["start"])] = best
                gold_names[(chunks[best][1], chunks[best][4])].append(best)
    callers = C.defaultdict(list)
    for index, c in enumerate(chunks):
        for name in c[8]:
            if (c[1], name) in gold_names:
                callers[(c[1], name)].append(index)

    def ref(index):
        c = chunks[index]
        return [c[0], c[6], c[7], c[3], c[5]]

    for task in gold:
        for g in task["gold"]["functions"]:
            path = g["path"]
            row = dict(task=task["id"], lang=task["row_lang"], repo=repo_name, commit=sha, path=path, start=g["start"], end=g["end"],
                       symbol=g.get("symbol"), file_indexed=path in files, file_why_not=why_out.get(path) if path not in files else None,
                       status="unmapped", file_out=sorted(out_edges.get(path, ())), file_in=sorted(in_edges.get(path, ())),
                       file_partners=sorted(partners.get(path, ())), files_in_repo=len(files), chunks_in_file=len(by_file.get(path, ())),
                       partner_out=sorted({t for p in partners.get(path, ()) for t in out_edges.get(p, ())}),
                       partner_in=sorted({t for p in partners.get(path, ()) for t in in_edges.get(p, ())}))
            index = mapped.get((task["id"], path, g["start"]))
            if index is not None:
                c = chunks[index]
                family, name, calls = c[1], c[4], c[8]
                callee_name, callee_scoped, caller_name, caller_scoped = set(), set(), set(), set()
                here = scope(path)
                for called in calls:
                    targets = definitions.get((family, called), [])
                    if len(targets) <= CFG.max_defs_per_name:
                        callee_name.update(t for t in targets if t != index)
                    callee_scoped.update(t for t in targets if t != index and chunks[t][0] in here)
                same_name = definitions.get((family, name), [])
                for caller in callers.get((family, name), []):
                    if caller == index:
                        continue
                    if len(same_name) <= CFG.max_defs_per_name:
                        caller_name.add(caller)
                    if path in scope(chunks[caller][0]):
                        caller_scoped.add(caller)
                row.update(status="mapped", chunk=ref(index), defs_of_name=len(same_name),
                           callers_name=[ref(i) for i in sorted(caller_name)], callees_name=[ref(i) for i in sorted(callee_name)],
                           callers_scoped=[ref(i) for i in sorted(caller_scoped)], callees_scoped=[ref(i) for i in sorted(callee_scoped)])
            writer.write(json.dumps(row, separators=(",", ":")) + "\n")
    if GOLD_FILES:  # one extra row per gold file, marked kind="file", with its import links only
        for task in gold:
            for path in task["gold"]["files"]:
                row = dict(kind="file", task=task["id"], lang=task["row_lang"], repo=repo_name, commit=sha, path=path,
                           file_indexed=path in files, file_why_not=why_out.get(path) if path not in files else None,
                           file_out=sorted(out_edges.get(path, ())), file_in=sorted(in_edges.get(path, ())),
                           file_partners=sorted(partners.get(path, ())),
                           partner_out=sorted({t for p in partners.get(path, ()) for t in out_edges.get(p, ())}),
                           partner_in=sorted({t for p in partners.get(path, ()) for t in in_edges.get(p, ())}))
                writer.write(json.dumps(row, separators=(",", ":")) + "\n")
    print(f"{repo_name} {sha[:10]}:{len(files)} files, {len(chunks)} chunks, parsed {len(missing)}, {time.time() - start:.0f} s", flush=True)
    return stats, C.Counter(v for v in why_out.values() if v not in ("not a supported language",))


def selftest():
    files = {"pkg/__init__.py", "pkg/a.py", "pkg/sub/__init__.py", "pkg/sub/b.py", "json.py", "x/src/lib/__init__.py", "x/src/lib/m.py",
             "app/main.ts", "app/util.ts", "app/dir/index.ts", "libs/core/src/thing.ts",
             "src/include/duckdb/common/f.hpp", "src/common/f.cpp", "core/io/file.h", "core/io/file.cpp"}
    r = Resolver(files, {"tsconfig.json": '{"compilerOptions":{"baseUrl":".",/*c*/"paths":{"@core/*":["libs/core/src/*"]},}}'},
                 {"libs/core/package.json": '{"name":"core-pkg"}'})
    assert r.python("pkg/sub/b.py", 2, "a", []) == {"pkg/a.py"}
    assert r.python("pkg/a.py", 1, "", ["sub"]) == {"pkg/sub/__init__.py"}
    assert r.python("pkg/a.py", 0, "pkg.sub", ["b"]) == {"pkg/sub/b.py"}
    assert r.python("pkg/a.py", 0, "pkg.sub.b", ["fn"]) == {"pkg/sub/b.py"}
    assert r.python("x/src/lib/m.py", 0, "lib", ["m"]) == {"x/src/lib/m.py"}
    assert r.python("pkg/a.py", 0, "os.path", []) == set()
    assert r.typescript("app/main.ts", "./util.js") == {"app/util.ts"}
    assert r.typescript("app/main.ts", "./dir") == {"app/dir/index.ts"}
    assert r.typescript("app/main.ts", "@core/thing") == {"libs/core/src/thing.ts"}
    assert r.typescript("app/main.ts", "core-pkg/lib/thing") == {"libs/core/src/thing.ts"}
    assert r.typescript("app/main.ts", "react") == set()
    assert r.include("src/common/f.cpp", '"', "duckdb/common/f.hpp") == {"src/include/duckdb/common/f.hpp"}
    assert r.include("core/io/file.cpp", '"', "file.h") == {"core/io/file.h"}
    assert r.include("core/io/file.cpp", "<", "vector") == set()
    py = get_language("python").parser().parse(b"from ..a.b import c as d, e\nimport x.y as z\ndef f():\n  from . import q\nfrom m import *\n").root_node
    assert sorted(python_imports(py), key=str) == sorted([[2, "a.b", ["c", "e"]], [0, "x.y", []], [1, "", ["q"]], [0, "m", []]], key=str)
    src = b"import {a} from './x.js';\nexport * from '../y';\nimport z = require('w');\nconst p = import('./dyn');\n"
    assert set(js_imports(get_language("typescript").parser().parse(src).root_node, src)) == {"./x.js", "../y", "w", "./dyn"}
    print("selftest passed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", nargs="?")
    ap.add_argument("repos", nargs="?")
    ap.add_argument("tasks", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--gold-files", action="store_true", help="also write one kind=file row per gold file")
    args = ap.parse_args()
    global GOLD_FILES
    GOLD_FILES = args.gold_files
    if args.selftest:
        selftest()
        return
    rows = json.load(open(args.rows, encoding="utf8"))
    wanted = {r["id"]: r for r in rows}
    tasks = {}
    for file in Path(args.tasks).glob("*.jsonl"):
        for line in open(file, encoding="utf8"):
            task = json.loads(line)
            if task["id"] in wanted:
                task["row_lang"] = wanted[task["id"]]["lang"]
                tasks[task["id"]] = task
    missing = set(wanted) - set(tasks)
    if missing:
        raise SystemExit(f"tasks not found: {sorted(missing)[:5]}")
    by_commit = C.defaultdict(list)
    for task in tasks.values():
        by_commit[(task["repo"], task["base_commit"])].append(task)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    start = time.time()
    resolved, left_out = C.defaultdict(C.Counter), C.defaultdict(C.Counter)
    temp = out / "gold_links.jsonl.gz.tmp"
    with ProcessPoolExecutor(max_workers=args.workers) as pool, gzip.open(temp, "wt", encoding="utf8") as writer:
        for repo in sorted({r for r, _ in by_commit}):
            cache = ParseCache(out / "parse" / (repo.replace("/", "__") + ".sqlite"))
            for (r, sha), group in sorted(by_commit.items()):
                if r == repo:
                    stats, why = build_commit(repo, Path(args.repos) / (repo.replace("/", "__") + ".git"), sha, group, cache, pool, writer)
                    resolved[repo].update(stats)
                    left_out[repo].update(why)
            cache.db.close()
    os.replace(temp, out / "gold_links.jsonl.gz")
    (out / "build_summary.json").write_text(json.dumps({"imports": resolved, "not_indexed": left_out, "seconds": time.time() - start}, indent=1), encoding="utf8")
    print(f"DONE {len(by_commit)} commits, {len(tasks)} tasks, {time.time() - start:.0f} s", flush=True)


if __name__ == "__main__":
    main()
