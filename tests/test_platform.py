import subprocess
import sys

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
    proc = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "True"
