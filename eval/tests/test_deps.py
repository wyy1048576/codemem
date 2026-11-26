"""deps: which third-party requirements the real fix of a task adds or raises.

The snippets are cut from the real dependency files of the task repos (the task ids are named).
"""

import pytest

from cmeval import deps
from cmeval.resplit import DEFAULT_DEPENDENCY_PATHS, match


def kinds(changes):
    return [(c.package, c.kind) for c in changes]


# ---- versions and bounds

def test_version_order():
    key = deps.version_key
    assert key("1.10") > key("1.9") and key("2.0") > key("2.0rc1") and key("1.0.0") == key("1")
    assert key("v0.0.0-20260526163538-3dc84a4a5aaa") > key("v0.0.0-20250101000000-aaaaaaaaaaaa")
    assert key("v1.82.2") > key("v1.82.1") and key("main") is None


def test_lower_bounds():
    assert deps.pep440_bound(">=2.11.0,!=2.14.1")[2] == "2.11.0"
    assert deps.pep440_bound("<4.0") is None and deps.pep440_bound("==1.4.*")[2] == "1.4.*"
    assert deps.pep440_bound("@ git+https://x/y.git@abc")[0] == "opaque"
    assert deps.npm_bound("^0.0.2-40")[2] == "0.0.2-40" and deps.npm_bound(">=1.2 <2 || ^0.9")[2] == "0.9"
    assert deps.npm_bound("*") is None and deps.npm_bound("github:user/repo#abc")[0] == "opaque"
    assert deps.cargo_bound(">=1.2, <2")[2] == "1.2" and deps.cargo_bound("0.11.0")[2] == "0.11.0"


# ---- one file

def test_requirements_pin_raised_lowered_added_removed():
    # home-assistant__core-177631 (aiohue), core-180411 (numpy), core-179723 (energyflip).
    old = "# homeassistant.components.hue\naiohue==4.8.1\n\nnumpy==2.5.2\nenergyflip-client==0.2.2\n"
    new = "# homeassistant.components.hue\naiohue==4.8.2\n\nnumpy==2.3.2\nenergyflip-api-client==0.3.0\n"
    changes = deps.file_changes("requirements_all.txt", old, new)
    assert kinds(changes) == [("aiohue", "raised"), ("energyflip-api-client", "added"), ("energyflip-client", "removed"),
                              ("numpy", "lowered")]
    assert (changes[0].old, changes[0].new) == ("aiohue ==4.8.1", "aiohue ==4.8.2")


def test_an_excluded_version_is_not_a_raise():
    # pandas-dev__pandas-66956: numexpr 2.14.1 is excluded, the minimum stays.
    old = "matplotlib>=3.10.5\nnumexpr>=2.11.0\n"
    new = "matplotlib>=3.10.5\nnumexpr>=2.11.0,!=2.14.1\n"
    assert kinds(deps.file_changes("requirements-dev.txt", old, new)) == [("numexpr", "other")]


def test_a_new_minimum_and_a_new_extra_are_needed():
    # vllm-project__vllm-53870: "mcp" becomes "mcp >= 2.0.0, < 3.0.0".
    assert kinds(deps.file_changes("requirements/common.txt", "anthropic >= 0.71.0\nmcp\n",
                                   "anthropic >= 0.71.0\nmcp >= 2.0.0, < 3.0.0\n")) == [("mcp", "raised")]
    assert kinds(deps.file_changes("r.txt", "uvicorn>=0.30\n", "uvicorn[standard]>=0.30\n")) == [("uvicorn", "added")]


def test_requirement_options_and_local_paths_are_not_packages():
    text = "-r requirements.txt\n-c homeassistant/package_constraints.txt\n--index-url https://x\n-e .\n./packages/a\nfoo==1 \\\n    --hash=sha256:abc\n"
    assert deps.parse_requirements_txt(text) == {"foo": ["foo ==1"]}


def test_a_new_constraint_counts_only_with_a_minimum():
    # home-assistant__core-185206 (graphql-core<3.3) and core-186164 (pycares==5.0.1).
    changes = deps.file_changes("homeassistant/package_constraints.txt", "aiohttp==3.13.3\n",
                                "aiohttp==3.13.3\ngraphql-core<3.3\npycares==5.0.1\n")
    assert kinds(changes) == [("graphql-core", "other"), ("pycares", "raised")]


def test_pyproject_tables_and_tool_settings():
    # pandas-dev__pandas-66972 removes hypothesis; pandas-67034 changes a ruff setting only.
    old = """[project]
dependencies = ['numpy>=1.26.0']
[project.optional-dependencies]
test = ['hypothesis>=6.116.0', 'pytest>=8.3.4']
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"os.remove".msg = "Do not use os.remove"
"""
    new = old.replace("'hypothesis>=6.116.0', ", "").replace('"os.remove"', '"os.unlink"')
    assert kinds(deps.file_changes("pyproject.toml", old, new)) == [("hypothesis", "removed")]
    assert deps.file_changes("pyproject.toml", new, new.replace("unlink", "rmdir")) == []


def test_pyproject_workspace_sources_are_local():
    # An airflow provider raises its minimum of another workspace member.
    old = """[project]
dependencies = ["apache-airflow>=2.11.0", "apache-airflow-providers-common-compat>=1.8.0", "asyncssh>=2.12.0"]
[tool.uv.sources]
apache-airflow = {workspace = true}
apache-airflow-providers-common-compat = {workspace = true}
"""
    new = old.replace("compat>=1.8.0", "compat>=1.10.0").replace("asyncssh>=2.12.0", "asyncssh>=2.14.0")
    assert kinds(deps.file_changes("providers/sftp/pyproject.toml", old, new)) == [("asyncssh", "raised")]


def test_conda_environment():
    # pandas environment.yml: conda and pip sections.
    old = "name: pandas-dev\ndependencies:\n  - python=3.11\n  - numexpr>=2.11.0\n  - pip:\n    - tzdata>=2022.7\n"
    new = old.replace("numexpr>=2.11.0", "numexpr>=2.12.0").replace("tzdata>=2022.7", "tzdata>=2022.7\n    - adbc-driver>=1.0")
    assert kinds(deps.file_changes("environment.yml", old, new)) == [("adbc-driver", "added"), ("numexpr", "raised")]


def test_home_assistant_manifest():
    old = '{"domain": "hue", "codeowners": ["@balloob"], "requirements": ["aiohue==4.8.1"]}'
    assert kinds(deps.file_changes("homeassistant/components/hue/manifest.json", old, old.replace("4.8.1", "4.8.2"))) == [
        ("aiohue", "raised")]
    assert deps.file_changes("homeassistant/components/hue/manifest.json", old, old.replace("@balloob", "@x")) == []


UV_LOCK = """version = 1
revision = 3

[[package]]
name = "apache-airflow-providers-ssh"
version = "4.1.0"
source = { editable = "providers/ssh" }

[[package]]
name = "paramiko"
version = "3.5.1"
source = { registry = "https://pypi.org/simple" }
"""


def test_uv_lock_versions_and_workspace_members():
    # apache__airflow-69669: paramiko 3.5.1 -> 4.0.0 and a new package invoke.
    new = UV_LOCK.replace('"3.5.1"', '"4.0.0"').replace("4.1.0", "4.2.0") + (
        '\n[[package]]\nname = "invoke"\nversion = "3.0.3"\nsource = { registry = "https://pypi.org/simple" }\n')
    assert kinds(deps.file_changes("uv.lock", UV_LOCK, new)) == [("invoke", "added"), ("paramiko", "raised")]
    assert deps.parse_python_lock(UV_LOCK)[1] == {"apache-airflow-providers-ssh"}


def test_lock_with_a_new_version_beside_the_old():
    # microsoft__playwright-42238: chokidar 4.0.3 comes in, 3.6.0 stays for another package.
    old = '{"lockfileVersion": 3, "packages": {"": {"name": "playwright-internal"}, "node_modules/chokidar": {"version": "3.6.0"}}}'
    new = ('{"lockfileVersion": 3, "packages": {"": {"name": "playwright-internal"}, "node_modules/chokidar": {"version": "4.0.3"},'
           ' "node_modules/x/node_modules/chokidar": {"version": "3.6.0"},'
           ' "packages/playwright-core": {"name": "playwright-core", "version": "1.60.0"},'
           ' "node_modules/playwright-core": {"resolved": "packages/playwright-core", "link": true}}}')
    changes = deps.file_changes("package-lock.json", old, new)
    assert kinds(changes) == [("chokidar", "raised")] and changes[0].new == "4.0.3 | 3.6.0"
    assert deps.parse_package_lock(new)[1] == {"playwright-core"}
    # A version between two old ones has no order to the image: it is a new download.
    assert deps.compare(["3.6.0", "5.0.0"], ["4.0.3", "5.0.0"], deps.file_type("package-lock.json")) == "changed"


def test_package_json_maps():
    old = '{"name": "markdown", "version": "1.0.0", "scripts": {"build": "x"}, "dependencies": {"@vscode/markdown-editor": "^0.0.2-37", "local": "file:../x"}}'
    new = old.replace("-37", "-40").replace('"version": "1.0.0"', '"version": "2.0.0"').replace('"x"}', '"y"}')
    assert kinds(deps.file_changes("extensions/markdown-language-features/package.json", old, new)) == [
        ("@vscode/markdown-editor", "raised")]


def test_pnpm_lock():
    # apache__airflow-70937 (the UI of airflow-core).
    old = "lockfileVersion: '9.0'\n\nimporters:\n  .:\n    dependencies:\n      monaco-editor:\n        specifier: ^0.55.1\n        version: 0.55.1\n\npackages:\n\n  '@babel/core@7.24.0':\n    resolution: {integrity: x}\n\n  monaco-editor@0.55.1:\n    resolution: {integrity: y}\n\nsnapshots:\n\n  monaco-editor@0.55.1: {}\n"
    new = old.replace("0.55.1", "0.56.0")
    assert deps.parse_pnpm_lock(old)[0] == {"@babel/core": ["7.24.0"], "monaco-editor": ["0.55.1"]}
    assert kinds(deps.file_changes("airflow-core/src/airflow/ui/pnpm-lock.yaml", old, new)) == [("monaco-editor", "raised")]


CARGO_LOCK = """version = 4

[[package]]
name = "gen-lsp-types"
version = "0.10.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "4cd635c5206acd03ea024d6b5902539e5c903de3afa220fdb5c94b583af77f4f"

[[package]]
name = "ruff_server"
version = "0.0.0"
dependencies = [
 "gen-lsp-types",
]
"""


def test_cargo_lock_and_toml():
    # astral-sh__ruff-27230: gen-lsp-types 0.10.0 -> 0.11.0. ruff_server is a crate of the workspace.
    new = CARGO_LOCK.replace('"0.10.0"', '"0.11.0"').replace('version = "0.0.0"', 'version = "0.0.1"')
    assert kinds(deps.file_changes("Cargo.lock", CARGO_LOCK, new)) == [("gen-lsp-types", "raised")]
    toml = '[workspace.dependencies]\ngen-lsp-types = { version = "0.10.0" }\nruff_db = { path = "crates/ruff_db" }\n'
    changed = toml.replace("0.10.0", "0.11.0").replace("crates/ruff_db", "crates/ruff_db2")
    assert kinds(deps.file_changes("Cargo.toml", toml, changed)) == [("gen-lsp-types", "raised")]
    crate = '[package]\nname = "ty"\n[dependencies]\nserde = { workspace = true }\n'
    assert deps.file_changes("crates/ty/Cargo.toml", crate, crate + 'anyhow = { workspace = true }\n') == []


GO_MOD = """module k8s.io/kubernetes

go 1.27.0

require (
	google.golang.org/grpc v1.82.1
	k8s.io/api v0.0.0
)

require github.com/x/y v1.0.0 // indirect

replace (
	k8s.io/api => ./staging/src/k8s.io/api
)
"""


def test_go_mod_and_vendor_modules():
    # kubernetes__kubernetes-141976: grpc v1.82.1 -> v1.82.2 in go.mod and vendor/modules.txt.
    changes = deps.file_changes("go.mod", GO_MOD, GO_MOD.replace("v1.82.1", "v1.82.2").replace("k8s.io/api v0.0.0", "k8s.io/api v0.0.1"))
    assert kinds(changes) == [("google.golang.org/grpc", "raised")]
    assert deps.parse_go_mod(GO_MOD)[0]["github.com/x/y"] == ["v1.0.0"]
    vendor = ("# google.golang.org/grpc v1.82.1\n## explicit; go 1.25.0\ngoogle.golang.org/grpc\n"
              "# k8s.io/api v0.0.0 => ./staging/src/k8s.io/api\n## explicit; go 1.27.0\n")
    assert kinds(deps.file_changes("vendor/modules.txt", vendor, vendor.replace("v1.82.1", "v1.82.2").replace(
        "v0.0.0 =>", "v0.0.1 =>"))) == [("google.golang.org/grpc", "raised")]


def test_npmrc_and_browsers_json():
    # microsoft__vscode-336697 (Electron) and microsoft__playwright-41836 (a WebKit build).
    npmrc = 'disturl="https://electronjs.org/headers"\ntarget="43.6.0"\nms_build_id="15274685"\nruntime="electron"\n'
    assert kinds(deps.file_changes(".npmrc", npmrc, npmrc.replace("43.6.0", "43.7.3"))) == [("electron", "raised")]
    browsers = '{"browsers": [{"name": "chromium", "revision": "1200"}, {"name": "webkit", "revision": "2331"}]}'
    assert kinds(deps.file_changes("packages/playwright-core/browsers.json", browsers, browsers.replace("2331", "2332"))) == [
        ("webkit", "raised")]


def test_a_file_that_does_not_parse_raises():
    with pytest.raises(deps.ParseError):
        deps.file_changes("uv.lock", "[[package]\n", "")


# ---- a whole fix

def _reader(files):
    return lambda side, path: files.get((side, path))


def test_analyse_lock_decides_and_installed_files():
    old_toml = '[project]\ndependencies = ["paramiko>=3.5.1,<4.0.0"]\n'
    new_toml = '[project]\ndependencies = ["paramiko>=4.0.0,<5.0.0"]\n'
    files = {("old", "providers/ssh/pyproject.toml"): old_toml, ("new", "providers/ssh/pyproject.toml"): new_toml,
             ("old", "uv.lock"): UV_LOCK, ("new", "uv.lock"): UV_LOCK.replace('"3.5.1"', '"4.0.0"'),
             ("old", "docs/requirements.txt"): "sphinx>=7\n", ("new", "docs/requirements.txt"): "sphinx>=8\n",
             ("new", "go.sum"): "x"}
    changed = [("providers/ssh/pyproject.toml", "providers/ssh/pyproject.toml"), ("uv.lock", "uv.lock"),
               ("docs/requirements.txt", "docs/requirements.txt"), ("go.sum", "go.sum"), ("README.md", "README.md")]
    result = deps.analyse(changed, _reader(files), ("uv.lock", "**/pyproject.toml"), DEFAULT_DEPENDENCY_PATHS, match)
    assert kinds(result.needed) == [("paramiko", "raised")] and result.needed[0].file == "uv.lock"
    assert [(c.file, c.kind) for c in result.other] == [("providers/ssh/pyproject.toml", "raised, locked by uv.lock"),
                                                        ("docs/requirements.txt", "raised, not installed from")]
    assert result.files == ["go.sum"]
    needed, weak = result.tags()
    assert needed == [{"file": "uv.lock", "package": "paramiko", "old": "3.5.1", "new": "4.0.0", "kind": "raised"}]
    assert weak["files"] == ["go.sum"] and len(weak["changes"]) == 2


def test_analyse_without_a_lock_the_manifest_decides():
    old = '[project]\ndependencies = ["numpy>=1.26"]\n'
    files = {("old", "pyproject.toml"): old, ("new", "pyproject.toml"): old.replace("1.26", "2.0")}
    result = deps.analyse([("pyproject.toml", "pyproject.toml")], _reader(files), ("pyproject.toml",), (), match)
    assert kinds(result.needed) == [("numpy", "raised")]


def test_analyse_skips_the_repo_packages_named_by_the_root_lock():
    # A crate of the workspace changes its version in Cargo.lock: not third-party.
    files = {("old", "Cargo.lock"): CARGO_LOCK, ("new", "Cargo.lock"): CARGO_LOCK.replace('"0.0.0"', '"0.1.0"')}
    result = deps.analyse([("Cargo.lock", "Cargo.lock")], _reader(files), ("Cargo.lock",), (), match)
    assert result.needed == [] and result.files == ["Cargo.lock"]


def test_analyse_records_a_file_that_does_not_parse():
    files = {("old", "uv.lock"): "[[package]\n", ("new", "uv.lock"): "x"}
    result = deps.analyse([("uv.lock", "uv.lock")], _reader(files), ("uv.lock",), (), match)
    assert result.needed == [] and "uv.lock" in result.errors and "unparsed" in result.tags()[1]
