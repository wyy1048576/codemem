"""codemem: local hybrid code search for coding agents."""

import os
import sys


def _one_openmp_thread() -> None:
    """Give OpenMP one thread in this process, and say so on stderr when that changes a setting."""
    changed = {name: value for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")
               if (value := os.environ.get(name)) not in (None, "1")}
    os.environ.update(dict.fromkeys(changed, "1"))
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    if changed and sys.stderr is not None:  # never stdout: the MCP server speaks its protocol there
        said = " and ".join(f"{name} from {value} to 1" for name, value in changed.items())
        try:
            sys.stderr.write(f"codemem: changed {said} for this process, because on macOS faiss-cpu and torch "
                             "each bring their own copy of OpenMP, and the two crash together when OpenMP runs "
                             "more than one thread.\n")
        except OSError:  # a closed stderr must not stop codemem from starting
            pass


# macOS: the faiss-cpu and torch wheels each bundle their own libomp, so a process that loads both
# has two copies of OpenMP. The second copy to start aborts the process ("OMP: Error #15") unless
# KMP_DUPLICATE_LIB_OK allows it. Then torch's copy binds a weak OpenMP symbol (__kmp_suspend_64) to
# FAISS's copy, loaded first, whose code segfaults on a thread of torch's copy. Only a thread that
# waits at a barrier of a team of several threads reaches that symbol, so OpenMP gets one thread
# whatever the environment says: OMP_NUM_THREADS becomes 1, and so does MKL_NUM_THREADS when it is
# set, because torch takes its thread count from it ahead of OMP_NUM_THREADS. Once set, both stay 1,
# so the note on stderr comes once per process. This must run before faiss or torch is imported.
if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    _one_openmp_thread()

__version__ = "0.2.0"
