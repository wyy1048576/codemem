"""Changes of third-party requirements in the real fix of a task.

A task image has the dependencies of the base commit, and the tests run with the network off. So
no agent can complete a task whose real fix needs a third-party package that the image does not
have. The rule (decided 2026-11-26): such a task leaves the candidate pool before sampling, in every
repo. "Needs" means: the fix changes the version of a third-party package, or adds one, in a file
that the recipe installs from, a lock file, or vendored third-party code, and the image does not
meet the new requirement.

The image is not known here. So the module approximates the last part with a fixed rule: a package
was added, its pin or lower bound was raised, or its source changed in a way that has no order (a
git commit, a URL). These are the changes of kind "added", "raised" and "changed". A lowered pin, a
removed package, a new upper bound, an excluded version or a new marker is of another kind. Each
change keeps the old and the new requirement text, so a person can audit it.

The module reads each dependency file whole, at the base commit and at the fix commit, and compares
the requirements that it declares. A diff hunk alone does not show the table or map that a line is
in (a pyproject.toml tool setting, the "scripts" of a package.json), so the whole file is parsed.

Two more rules make the count precise:

- A package of the repo itself is not third-party: uv workspace members, Cargo crates without a
  registry source, npm workspace links, Go modules replaced by a local path (kubernetes staging/).
  They are found in the lock files of the fix commit and in the changed files.
- A manifest that a lock file pins (pyproject.toml under uv.lock, package.json beside
  package-lock.json or pnpm-lock.yaml, Cargo.toml under Cargo.lock) does not decide: the image
  installs the versions of the lock. Its changes are recorded with the kind "locked", and the
  lock file decides.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

# Kinds of a change. The first three mean that the image may not meet the new requirement.
NEEDED = ("added", "raised", "changed")
OTHER = ("lowered", "removed", "other", "locked")

# Lock files that pin the packages of a manifest in the same folder or a folder above it.
LOCKS_OF = {
    "pyproject.toml": ("uv.lock", "poetry.lock", "pdm.lock"),
    "package.json": ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"),
    "Cargo.toml": ("Cargo.lock",),
}
# Root files that name the packages of the repo itself.
ROOT_LOCKS = ("uv.lock", "Cargo.lock", "package-lock.json", "go.mod")

# read(side, path): the text of a file at the base commit (side "old") or the fix commit ("new"),
# or None when the file does not exist there.
Reader = Callable[[str, str], "str | None"]


@dataclass(frozen=True)
class Change:
    file: str
    package: str
    old: str | None  # the requirement text before the fix (None: not declared)
    new: str | None  # after the fix
    kind: str

    def to_dict(self) -> dict:
        return asdict(self)


class ParseError(ValueError):
    pass


# ---- versions

_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)(.*)")
_TIMESTAMP_RE = re.compile(r"(\d{14})")


def version_key(text: str) -> tuple | None:
    """A sort key for a version (PEP 440, semver, Go): the numbers, then release above pre-release,
    then the timestamp of a Go pseudo-version, then the rest. None when it does not start with a number."""
    m = _VERSION_RE.match(text.strip())
    if not m:
        return None
    nums = tuple(int(x) for x in m.group(1).split("."))
    rest = m.group(2).rstrip(".*")
    nums = nums + (0,) * max(0, 6 - len(nums))
    release = 1 if rest == "" or rest.startswith(("+", ".post", "-post", ".dev0+")) else 0
    stamp = _TIMESTAMP_RE.search(rest)
    return nums, release, stamp.group(1) if stamp else "", rest


# A lower bound: ("version", key, text), ("opaque", text) for a source without an order, or None.
Bound = tuple | None

_PEP440_CLAUSE = re.compile(r"\s*(===|==|~=|>=|<=|!=|>|<)\s*([^\s,;]+)")


def pep440_bound(spec: str) -> Bound:
    """The lower bound of a PEP 440 specifier such as ">=1.2,<2" or "==1.4.*"."""
    spec = spec.strip()
    if spec.startswith("@"):
        return ("opaque", spec[1:].strip())
    best = None
    for clause in spec.split(","):
        m = _PEP440_CLAUSE.match(clause)
        if not m or m.group(1) in ("<", "<=", "!="):
            continue
        key = version_key(m.group(2))
        if key is not None and (best is None or key > best[1]):
            best = ("version", key, m.group(2))
    return best


_NPM_VERSION = re.compile(r"v?\d+(?:\.(?:\d+|x|\*))*(?:-[0-9A-Za-z.-]+)?")


def npm_bound(spec: str) -> Bound:
    """The lower bound of an npm range: the lowest alternative of "a || b", each alternative its
    first version that is not after "<". A git, URL or tag source is opaque."""
    spec = spec.strip()
    if spec.startswith("npm:"):
        spec = spec.rsplit("@", 1)[-1] if "@" in spec[4:] else ""
    if spec in ("", "*", "x", "latest", "next"):
        return None
    if "://" in spec or spec.startswith(("git", "github:", "gitlab:", "bitbucket:")) or re.match(r"^[\w.-]+/[\w.-]+", spec):
        return ("opaque", spec)
    lows = []
    for alternative in spec.split("||"):
        low = None
        for token in re.split(r"\s+", alternative.strip()):
            if token.startswith("<") or token == "-":
                continue
            m = _NPM_VERSION.search(token)
            if m:
                low = m.group(0)
                break
        if low is None:
            return None  # one alternative takes any version
        lows.append(low)
    if not lows:
        return None
    key, text = min((version_key(v.replace("x", "0").replace("*", "0")), v) for v in lows)
    return ("version", key, text) if key is not None else ("opaque", spec)


def cargo_bound(spec: str) -> Bound:
    """The lower bound of a Cargo version requirement such as "1.2", "=1.2.3" or ">=1, <2"."""
    best = None
    for clause in spec.split(","):
        clause = clause.strip()
        if clause.startswith("<") or clause in ("", "*"):
            continue
        m = re.search(r"\d+(?:\.(?:\d+|\*))*(?:-[0-9A-Za-z.-]+)?", clause)
        if m:
            key = version_key(m.group(0).replace("*", "0"))
            if key is not None and (best is None or key > best[1]):
                best = ("version", key, m.group(0))
    return best


def exact_bound(spec: str) -> Bound:
    """An exact version (a lock file, a Go module): it is its own lower bound."""
    key = version_key(spec)
    return ("version", key, spec) if key is not None else ("opaque", spec)


# ---- the files: each parser gives {package: [requirement texts]} and the local package names

def normalize_python(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


_PY_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")


def python_requirement(line: str) -> tuple[str, str] | None:
    """(normalized name, requirement text) of one PEP 508 requirement, or None for a local path."""
    line = line.strip()
    m = _PY_REQ.match(line)
    if not m:
        return None
    name, extras, rest = m.group(1), m.group(2) or "", m.group(3)
    rest = rest.split(";", 1)
    spec = rest[0].strip()
    marker = f"; {rest[1].strip()}" if len(rest) > 1 else ""
    extras = "[" + ",".join(sorted(e.strip() for e in extras.strip("[]").split(",") if e.strip())) + "]" if extras else ""
    return normalize_python(name), f"{normalize_python(name)}{extras}{(' ' + spec) if spec else ''}{marker}"


def parse_requirements_txt(text: str) -> dict[str, list[str]]:
    """A pip requirements or constraints file. Options (-r, -c, --index-url) and local paths are not packages."""
    out: dict[str, list[str]] = {}
    joined = re.sub(r"\\\n", " ", text)
    for raw in joined.splitlines():
        line = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].strip()
        line = re.sub(r"\s--hash[= ]\S+", "", line).strip()
        if not line:
            continue
        if line.startswith("-"):
            m = re.match(r"-e\s+\S*#egg=([A-Za-z0-9._-]+)", line)
            if m and "://" in line:
                out.setdefault(normalize_python(m.group(1)), []).append(line)
            continue
        if line.startswith((".", "/", "file:")):
            continue
        req = python_requirement(line)
        if req:
            out.setdefault(req[0], []).append(req[1])
    return out


def _toml(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ParseError(str(exc)) from exc


def _json(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(str(exc)) from exc
    return data if isinstance(data, dict) else {}


def parse_pyproject(text: str) -> tuple[dict[str, list[str]], set[str]]:
    """The requirements of [project], [project.optional-dependencies], [dependency-groups],
    [build-system] and Poetry's tables. Names with a workspace or path source are local."""
    data = _toml(text)
    out: dict[str, list[str]] = {}
    local: set[str] = set()
    project = data.get("project", {})
    lines = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        lines += group
    for group in data.get("dependency-groups", {}).values():
        lines += [x for x in group if isinstance(x, str)]
    lines += data.get("build-system", {}).get("requires", [])
    for line in lines:
        req = python_requirement(line) if isinstance(line, str) else None
        if req:
            out.setdefault(req[0], []).append(req[1])
    poetry = data.get("tool", {}).get("poetry", {})
    tables = [poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})]
    tables += [g.get("dependencies", {}) for g in poetry.get("group", {}).values()]
    for table in tables:
        for name, value in table.items():
            if name == "python":
                continue
            if isinstance(value, dict) and ("path" in value or "develop" in value):
                local.add(normalize_python(name))
                continue
            spec = value if isinstance(value, str) else (value.get("version") or value.get("git") or "")
            out.setdefault(normalize_python(name), []).append(f"{normalize_python(name)} {spec}".strip())
    for name, source in data.get("tool", {}).get("uv", {}).get("sources", {}).items():
        if isinstance(source, dict) and (source.get("workspace") or "path" in source):
            local.add(normalize_python(name))
    return out, local


def parse_conda_env(text: str) -> dict[str, list[str]]:
    """The packages of a conda environment file (environment.yml), with its pip section."""
    out: dict[str, list[str]] = {}
    inside = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "-")):
            inside = line.startswith("dependencies:")
            continue
        m = re.match(r"\s*-\s+(.+)$", line)
        if not inside or not m or m.group(1).endswith(":"):
            continue
        item = m.group(1).strip().strip("'\"")
        item = re.sub(r"^([A-Za-z0-9._-]+)\s*=(?!=)", r"\1==", item)  # conda "x=1.2" means "x==1.2.*"
        item = re.sub(r"^([A-Za-z0-9._-]+)\s+(\d)", r"\1==\2", item)  # conda "x 1.2"
        req = python_requirement(item)
        if req:
            out.setdefault(req[0], []).append(req[1])
    return out


def parse_ha_manifest(text: str) -> dict[str, list[str]]:
    """The "requirements" list of a home-assistant integration manifest."""
    out: dict[str, list[str]] = {}
    for line in _json(text).get("requirements", []):
        req = python_requirement(line) if isinstance(line, str) else None
        if req:
            out.setdefault(req[0], []).append(req[1])
    return out


def parse_python_lock(text: str) -> tuple[dict[str, list[str]], set[str]]:
    """uv.lock, poetry.lock or pdm.lock: the locked version of each package. A package from the
    workspace, a folder or an editable path is local."""
    out: dict[str, list[str]] = {}
    local: set[str] = set()
    for package in _toml(text).get("package", []):
        name = normalize_python(str(package.get("name", "")))
        source = package.get("source", {})
        if isinstance(source, dict) and (set(source) & {"editable", "virtual", "directory", "path"}
                                         or source.get("type") in ("directory", "file")):
            local.add(name)
            continue
        out.setdefault(name, []).append(str(package.get("version", "")))
    return out, local


_NPM_DEP_MAPS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
_NPM_LOCAL = ("file:", "link:", "workspace:", "portal:")


def parse_package_json(text: str) -> tuple[dict[str, list[str]], set[str]]:
    """The dependency maps of a package.json. A file, link or workspace dependency is local."""
    data = _json(text)
    out: dict[str, list[str]] = {}
    local = {data["name"]} if isinstance(data.get("name"), str) else set()
    for key in _NPM_DEP_MAPS:
        table = data.get(key)
        for name, spec in (table.items() if isinstance(table, dict) else ()):
            if isinstance(spec, str) and spec.startswith(_NPM_LOCAL):
                local.add(name)
            elif isinstance(spec, str):
                out.setdefault(name, []).append(spec)
    return out, local


def parse_package_lock(text: str) -> tuple[dict[str, list[str]], set[str]]:
    """package-lock.json (lockfileVersion 2 or 3): the versions of each package under node_modules.
    A link and a workspace folder are local."""
    data = _json(text)
    packages = data.get("packages")
    if not isinstance(packages, dict):
        raise ParseError("no 'packages' map (lockfileVersion 1 is not read)")
    out: dict[str, list[str]] = {}
    local: set[str] = set()
    for key, entry in packages.items():
        if not isinstance(entry, dict) or key == "":
            continue
        if "node_modules/" not in key:
            if isinstance(entry.get("name"), str):
                local.add(entry["name"])
            continue
        name = key.rsplit("node_modules/", 1)[1]
        if entry.get("link"):
            local.add(name)
            continue
        if isinstance(entry.get("version"), str):
            out.setdefault(name, []).append(entry["version"])
    return out, local


def parse_pnpm_lock(text: str) -> tuple[dict[str, list[str]], set[str]]:
    """pnpm-lock.yaml: the keys of its "packages:" section, as name@version."""
    out: dict[str, list[str]] = {}
    inside = False
    for line in text.splitlines():
        if line and not line.startswith(" "):
            inside = line.startswith("packages:")
            continue
        m = re.match(r"^  ['\"]?/?((?:@[^@/\s]+/)?[^@\s'\"]+)@([^('\":\s]+)", line) if inside else None
        if m:
            out.setdefault(m.group(1), []).append(m.group(2))
    return out, set()


def parse_cargo_toml(text: str) -> tuple[dict[str, list[str]], set[str]]:
    """The dependency tables of a Cargo.toml (also [workspace.dependencies] and target tables).
    A path dependency is local. A "workspace = true" entry is decided by the workspace table."""
    data = _toml(text)
    out: dict[str, list[str]] = {}
    local: set[str] = set()
    if isinstance(data.get("package", {}).get("name"), str):
        local.add(data["package"]["name"])
    tables = []
    for section in (data, data.get("workspace", {})):
        tables += [section.get(k, {}) for k in ("dependencies", "dev-dependencies", "build-dependencies")]
    for target in data.get("target", {}).values():
        tables += [target.get(k, {}) for k in ("dependencies", "dev-dependencies", "build-dependencies")]
    for table in tables:
        for key, value in table.items():
            if isinstance(value, dict):
                name = value.get("package", key)
                if "path" in value:
                    local.add(name)
                    continue
                if value.get("workspace"):
                    continue
                spec = value.get("version") or (f"git {value['git']} {value.get('rev') or value.get('tag') or value.get('branch') or ''}".strip()
                                                if "git" in value else "")
            else:
                name, spec = key, str(value)
            out.setdefault(name, []).append(spec)
    return out, local


def parse_cargo_lock(text: str) -> tuple[dict[str, list[str]], set[str]]:
    """Cargo.lock: a package without a source is a crate of the workspace."""
    out: dict[str, list[str]] = {}
    local: set[str] = set()
    for package in _toml(text).get("package", []):
        name = str(package.get("name", ""))
        if "source" not in package:
            local.add(name)
            continue
        source = str(package["source"])
        version = str(package.get("version", ""))
        out.setdefault(name, []).append(version if source.startswith("registry+") else f"{version} {source}")
    return out, local


def parse_go_mod(text: str) -> tuple[dict[str, list[str]], set[str]]:
    """The require and replace directives of a go.mod. A module replaced by a local path is local."""
    out: dict[str, list[str]] = {}
    local: set[str] = set()
    block = None
    replaced: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if line.endswith("(") and line.split()[0] in ("require", "replace", "exclude", "retract"):
            block = line.split()[0]
            continue
        if line == ")":
            block = None
            continue
        words = line.split()
        if block is None:
            if words[0] == "module" and len(words) > 1:
                local.add(words[1])
                continue
            if words[0] in ("require", "replace"):
                block_now, words = words[0], words[1:]
            else:
                continue
        else:
            block_now = block
        if block_now == "require" and len(words) >= 2:
            out.setdefault(words[0], []).append(words[1])
        elif block_now == "replace" and "=>" in words:
            i = words.index("=>")
            target = words[i + 1:]
            if target and target[0].startswith((".", "/")):
                local.add(words[0])
            elif len(target) >= 2:
                replaced[words[0]] = f"{target[0]} {target[1]}"
    for module, target in replaced.items():
        out[module] = [f"=> {target}"]
    return out, local


def parse_go_vendor(text: str) -> tuple[dict[str, list[str]], set[str]]:
    """vendor/modules.txt: the "# module version [=> replacement]" lines."""
    out: dict[str, list[str]] = {}
    local: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^# (\S+) (\S+)(?: => (\S+)(?: (\S+))?)?\s*$", line)
        if not m:
            continue
        module, version, target, target_version = m.groups()
        if target and target.startswith((".", "/")):
            local.add(module)
        elif target:
            out.setdefault(module, []).append(f"=> {target} {target_version or ''}".strip())
        else:
            out.setdefault(module, []).append(version)
    return out, local


def parse_browsers_json(text: str) -> dict[str, list[str]]:
    """playwright-core's browsers.json: the browser builds that `playwright install` gets."""
    out: dict[str, list[str]] = {}
    for browser in _json(text).get("browsers", []):
        if isinstance(browser, dict) and "name" in browser:
            out.setdefault(str(browser["name"]), []).append(str(browser.get("revision", "")))
    return out


def parse_npmrc(text: str) -> dict[str, list[str]]:
    """An .npmrc with runtime and target (vscode): the Electron or Node.js version that native
    modules are built for, and that `npm run electron` downloads."""
    values = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([\w-]+)\s*=\s*\"?([^\"]*)\"?\s*$", line)
        if m:
            values[m.group(1)] = m.group(2)
    if values.get("runtime") and values.get("target"):
        return {values["runtime"]: [values["target"]]}
    return {}


def parse_vcpkg_json(text: str) -> dict[str, list[str]]:
    """vcpkg.json: the "dependencies" list and the "overrides" versions."""
    data = _json(text)
    out: dict[str, list[str]] = {}
    for dep in data.get("dependencies", []):
        if isinstance(dep, str):
            out.setdefault(dep, []).append("")
        elif isinstance(dep, dict) and "name" in dep:
            out.setdefault(dep["name"], []).append(str(dep.get("version>=", "")))
    for override in data.get("overrides", []):
        if isinstance(override, dict) and "name" in override:
            out.setdefault(override["name"], []).append(str(override.get("version", "")))
    return out


@dataclass(frozen=True)
class FileType:
    name: str
    parse: Callable[[str], object]
    bound: Callable[[str], Bound]
    lock: bool = False  # versions are exact, and each new version is a new download
    constraints: bool = False  # a pip constraints file: a line limits a package, it does not add one


def _pep440_of_requirement(text: str) -> Bound:
    req = text.split(";", 1)[0]
    m = re.match(r"^[A-Za-z0-9._-]+(?:\[[^\]]*\])?\s*(.*)$", req)
    return pep440_bound(m.group(1) if m else req)


def _go_bound(text: str) -> Bound:
    if text.startswith("=>"):
        return ("opaque", text)
    return exact_bound(text)


def _poetry_or_pep440(text: str) -> Bound:
    spec = text.split(" ", 1)[1] if " " in text else ""
    if spec[:1].isdigit() or spec.startswith(("^", "~")) and not spec.startswith("~="):
        return npm_bound(spec)
    return _pep440_of_requirement(text)


def file_type(path: str) -> FileType | None:
    """The parser for a dependency file, by its name. None: no parser (the file is only listed)."""
    name = PurePosixPath(path).name
    if name == "pyproject.toml":
        return FileType("pyproject", parse_pyproject, _poetry_or_pep440)
    if name.endswith(".txt") and name not in ("modules.txt",):
        return FileType("requirements", parse_requirements_txt, _pep440_of_requirement, constraints="constraint" in name)
    if re.fullmatch(r"environment.*\.ya?ml", name):
        return FileType("conda", parse_conda_env, _pep440_of_requirement)
    if name == "manifest.json":
        return FileType("ha-manifest", parse_ha_manifest, _pep440_of_requirement)
    if name in ("uv.lock", "poetry.lock", "pdm.lock"):
        return FileType("python-lock", parse_python_lock, exact_bound, lock=True)
    if name == "package.json":
        return FileType("package.json", parse_package_json, npm_bound)
    if name in ("package-lock.json", "npm-shrinkwrap.json"):
        return FileType("npm-lock", parse_package_lock, exact_bound, lock=True)
    if name == "pnpm-lock.yaml":
        return FileType("pnpm-lock", parse_pnpm_lock, exact_bound, lock=True)
    if name == "Cargo.toml":
        return FileType("cargo", parse_cargo_toml, cargo_bound)
    if name == "Cargo.lock":
        return FileType("cargo-lock", parse_cargo_lock, exact_bound, lock=True)
    if name == "go.mod":
        return FileType("go.mod", parse_go_mod, _go_bound)
    if name == "modules.txt":
        return FileType("go-vendor", parse_go_vendor, _go_bound, lock=True)
    if name == "browsers.json":
        return FileType("browsers", parse_browsers_json, exact_bound, lock=True)
    if name == ".npmrc":
        return FileType("npmrc", parse_npmrc, exact_bound, lock=True)
    if name == "vcpkg.json":
        return FileType("vcpkg", parse_vcpkg_json, exact_bound)
    return None


def parse(path: str, text: str | None) -> tuple[dict[str, list[str]], set[str]]:
    """({package: [requirement texts]}, local names) of one dependency file. Raises ParseError."""
    kind = file_type(path)
    if kind is None or text is None:
        return {}, set()
    result = kind.parse(text)
    return result if isinstance(result, tuple) else (result, set())


# ---- comparing two versions of a file

def _bounds(texts: list[str], bound: Callable[[str], Bound]) -> tuple[tuple | None, set[str]]:
    versions, opaque = [], set()
    for text in texts:
        b = bound(text)
        if b is None:
            continue
        if b[0] == "opaque":
            opaque.add(b[1])
        else:
            versions.append(b[1])
    return (max(versions) if versions else None), opaque


def _extras(text: str) -> set[str]:
    m = re.match(r"^[A-Za-z0-9._-]+\[([^\]]*)\]", text)
    return {e for e in m.group(1).split(",") if e} if m else set()


def compare(old: list[str] | None, new: list[str] | None, kind: FileType) -> str | None:
    """The kind of change of one package between two versions of a file, or None when the same."""
    if old is None and kind.constraints:
        old = [""]  # a new constraint: only a new minimum or pin can need another version
    if old is None:
        return "added"
    if new is None:
        return "removed"
    if sorted(old) == sorted(new):
        return None
    if kind.lock:
        fresh = [v for v in new if v not in old]
        if not fresh:
            return "removed"  # a version less, none new
        old_keys = [k for k in (exact_bound(v) for v in old) if k[0] == "version"]
        result = "other"
        for v in fresh:
            b = exact_bound(v)
            if b[0] == "opaque" or not old_keys:
                return "changed"
            if b[1] > max(k[1] for k in old_keys):
                result = "raised"
            elif b[1] < min(k[1] for k in old_keys):
                result = "lowered" if result == "other" else result
            else:
                return "changed"
        return result
    old_low, old_opaque = _bounds(old, kind.bound)
    new_low, new_opaque = _bounds(new, kind.bound)
    if new_opaque - old_opaque:
        return "changed"
    if any(_extras(n) - set().union(*(_extras(o) for o in old)) for n in new):
        return "added"  # a new extra brings new packages
    if new_low is None:
        return "other"
    if old_low is None:
        return "changed" if old_opaque else "raised"
    if new_low > old_low:
        return "raised"
    if new_low < old_low:
        return "lowered"
    return "other"


def _text(texts: list[str] | None) -> str | None:
    return None if texts is None else " | ".join(texts)


def file_changes(path: str, old_text: str | None, new_text: str | None, local: set[str] | frozenset = frozenset()) -> list[Change]:
    """The changed requirements of one file, without the packages of the repo itself. Raises ParseError."""
    kind = file_type(path)
    if kind is None:
        return []
    old, old_local = parse(path, old_text)
    new, new_local = parse(path, new_text)
    skip = set(local) | old_local | new_local
    changes = []
    for package in sorted(set(old) | set(new)):
        if package in skip:
            continue
        how = compare(old.get(package), new.get(package), kind)
        if how:
            changes.append(Change(path, package, _text(old.get(package)), _text(new.get(package)), how))
    return changes


# ---- a whole fix

def local_packages(read: Reader) -> set[str]:
    """Names of the repo's own packages, from the root lock files at the fix commit."""
    names: set[str] = set()
    for path in ROOT_LOCKS:
        try:
            names |= parse(path, read("new", path))[1]
        except ParseError:
            pass
    return names


def lock_of(path: str, read: Reader) -> str | None:
    """The lock file that pins a manifest: in its folder or a folder above it, at the fix commit."""
    name = PurePosixPath(path).name
    if name not in LOCKS_OF:
        return None
    folder = PurePosixPath(path).parent
    while True:
        for lock in LOCKS_OF[name]:
            candidate = str(folder / lock) if str(folder) != "." else lock
            if read("new", candidate) is not None:
                return candidate
        if str(folder) in (".", "/", ""):
            return None
        folder = folder.parent


@dataclass
class Analysis:
    needed: list[Change]           # added, raised or changed, in a file the image installs from
    other: list[Change]            # every other change of a requirement, with the reason as kind
    files: list[str]               # dependency files that changed with no requirement change
    errors: dict[str, str]         # file: why it could not be parsed

    def tags(self) -> tuple[list[dict], dict]:
        """(the precise tag, the weak tag) as they go into a task row."""
        weak = {"changes": [c.to_dict() for c in self.other], "files": self.files}
        if self.errors:
            weak["unparsed"] = self.errors
        return [c.to_dict() for c in self.needed], weak


def analyse(files: list[tuple[str, str | None]], read: Reader, installed: tuple[str, ...], known: tuple[str, ...],
            match: Callable[[str, tuple[str, ...]], str | None]) -> Analysis:
    """The requirement changes of a fix. `files` are (path after the fix, path before it) of the files
    that the fix changes outside the code and the tests. `installed` are the globs of files the image
    installs from (the recipe's dependency_paths), `known` the globs of other dependency files: their
    changes are recorded, never needed."""
    result = Analysis([], [], [], {})
    chosen = [(p, o) for p, o in files if match(p, installed) or match(p, known)]
    if not chosen:
        return result
    local = local_packages(read)
    for path, old_path in chosen:
        if file_type(path) is None:
            result.files.append(path)
            continue
        try:
            changes = file_changes(path, read("old", old_path or path), read("new", path), local)
        except ParseError as exc:
            result.errors[path] = str(exc)[:200]
            continue
        if not changes:
            result.files.append(path)
            continue
        lock = lock_of(path, read)
        for change in changes:
            if not match(path, installed):
                result.other.append(Change(change.file, change.package, change.old, change.new,
                                           f"{change.kind}, not installed from"))
            elif lock and change.kind in NEEDED:
                result.other.append(Change(change.file, change.package, change.old, change.new,
                                           f"{change.kind}, locked by {lock}"))
            elif change.kind in NEEDED:
                result.needed.append(change)
            else:
                result.other.append(change)
    return result
