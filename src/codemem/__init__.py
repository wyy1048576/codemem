"""codemem: local hybrid code search for coding agents."""

import os
import sys

# macOS: the faiss-cpu and torch wheels each bundle their own libomp. When both start
# OpenMP, the second copy aborts the process ("OMP: Error #15"). Allowing the duplicate
# alone segfaults, so we also limit OpenMP to one thread. This must run before faiss
# or torch is imported. setdefault keeps any value the user sets.
if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")

__version__ = "0.2.0"
