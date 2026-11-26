import json
import os
import subprocess
import sys

import pytest

# Runs in a child process: an OpenMP clash aborts the whole interpreter.
SCRIPT = """
import codemem.store
import faiss
import numpy as np
index = faiss.IndexIDMap2(faiss.IndexFlatIP(64))
vecs = np.random.rand(5000, 64).astype("float32")
index.add_with_ids(vecs, np.arange(5000).astype("int64"))
index.search(vecs[:50], 3)
import torch
a = torch.rand(256, 256)
print(float((a @ a).sum()) > 0)
"""


def test_faiss_then_torch_does_not_abort():
    pytest.importorskip("torch")  # an environment built without it has one OpenMP, and nothing to clash
    proc = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "True"


# Imports codemem in a fresh process whose sys.platform reads as argv[1] (on a Mac, "darwin" changes
# nothing), and writes the settings it ends up with to the file argv[2], so that stdout holds only what
# the import printed.
IMPORT = """
import json, os, sys
sys.platform = sys.argv[1]
import codemem
with open(sys.argv[2], "w") as f:
    json.dump({name: os.environ.get(name) for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "KMP_DUPLICATE_LIB_OK")}, f)
"""


def import_codemem(tmp_path, platform, **settings):
    """The thread settings inside a fresh process after `import codemem`, and what the import printed on
    stdout and stderr. The process starts with these settings (None: unset) and nothing else of OpenMP's."""
    env = {k: v for k, v in os.environ.items() if k not in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "KMP_DUPLICATE_LIB_OK")}
    env.update({name: value for name, value in settings.items() if value is not None})
    out = tmp_path / "settings.json"
    proc = subprocess.run([sys.executable, "-c", IMPORT, platform, str(out)], env=env, capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(out.read_text()), proc.stdout, proc.stderr


def test_on_macos_openmp_gets_one_thread_and_stderr_says_what_changed(tmp_path):
    settings, stdout, stderr = import_codemem(tmp_path, "darwin", OMP_NUM_THREADS="4")
    assert settings == {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": None, "KMP_DUPLICATE_LIB_OK": "TRUE"}
    assert stdout == ""  # the MCP server speaks its protocol there
    assert len(stderr.splitlines()) == 1, stderr
    assert stderr.startswith("codemem: changed OMP_NUM_THREADS from 4 to 1 ") and "copy of OpenMP" in stderr


@pytest.mark.parametrize("value", [None, "1"], ids=["unset", "1"])
def test_on_macos_nothing_is_said_when_openmp_has_one_thread_already(tmp_path, value):
    settings, stdout, stderr = import_codemem(tmp_path, "darwin", OMP_NUM_THREADS=value)
    assert settings["OMP_NUM_THREADS"] == "1"
    assert (stdout, stderr) == ("", "")


def test_on_macos_mkl_num_threads_gets_one_thread_too(tmp_path):
    # torch takes its OpenMP thread count from MKL_NUM_THREADS ahead of OMP_NUM_THREADS
    settings, stdout, stderr = import_codemem(tmp_path, "darwin", OMP_NUM_THREADS="4", MKL_NUM_THREADS="8")
    assert settings["OMP_NUM_THREADS"] == settings["MKL_NUM_THREADS"] == "1"
    assert stdout == ""
    assert len(stderr.splitlines()) == 1 and "OMP_NUM_THREADS from 4 to 1 and MKL_NUM_THREADS from 8 to 1" in stderr


def test_elsewhere_the_thread_settings_are_left_alone(tmp_path):
    # no clash on Linux or Windows; the eval's Linux containers set four threads on purpose
    settings, stdout, stderr = import_codemem(tmp_path, "linux", OMP_NUM_THREADS="4", MKL_NUM_THREADS="4")
    assert settings == {"OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "KMP_DUPLICATE_LIB_OK": None}
    assert (stdout, stderr) == ("", "")
