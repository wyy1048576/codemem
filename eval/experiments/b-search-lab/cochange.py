"""Files changed together, from the local git history (bare clones, read only), for experiment 13.

    ./run.sh cochange.py <repo>      -> out/cochange-<repo>.npz

Every non-merge commit reachable from the clone's HEAD, with its committer time and the files it
changed (`git log --no-merges --name-only --no-renames`). Commits touching more than 30 files
(mass renames, reformatting) are dropped, so are files the index snapshot does not hold (their
chunks could not be returned anyway). Kept: commits sorted by time, and per commit the snapshot's
file numbers (lab_common.Index.file_no). Per task only commits older than the issue are used
(core-side, `CoChange.counts`), so the fix and everything after it are never counted."""
from __future__ import annotations

import subprocess
import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L

GIT = {"vllm": L.ROOT / ".cache/repos/vllm-history.git", "pandas": L.ROOT / ".cache/repos/pandas-history.git"}
MAX_FILES = 30


def main() -> None:
    repo = sys.argv[1]
    ix = L.Index(repo, vectors=False)
    log = subprocess.run(["git", "-C", str(GIT[repo]), "log", "--no-merges", "--no-renames", "--name-only",
                          "--format=@@%H %ct", "HEAD"], capture_output=True, text=True, check=True).stdout
    times, ptr, files = [], [0], []
    n_all = n_big = n_none = 0
    for block in log.split("@@")[1:]:
        lines = [x for x in block.split("\n") if x.strip()]
        head, paths = lines[0], lines[1:]
        n_all += 1
        if len(paths) > MAX_FILES:
            n_big += 1
            continue
        nums = sorted({ix.file_no[p] for p in paths if p in ix.file_no})
        if not nums:
            n_none += 1
            continue
        times.append(int(head.split()[1]))
        files.extend(nums)
        ptr.append(len(files))
    times_a = np.array(times, dtype=np.int64)
    order = np.argsort(times_a, kind="stable")
    ptr_a = np.array(ptr, dtype=np.int64)
    files_a = np.array(files, dtype=np.int32)
    # re-pack in time order
    new_files, new_ptr = [], [0]
    for c in order:
        seg = files_a[ptr_a[c]:ptr_a[c + 1]]
        new_files.append(seg)
        new_ptr.append(new_ptr[-1] + len(seg))
    np.savez(L.OUT / f"cochange-{repo}.npz", times=times_a[order], ptr=np.array(new_ptr, dtype=np.int64),
             files=np.concatenate(new_files) if new_files else np.zeros(0, np.int32), n_files=len(ix.paths))
    print(f"{repo}: {n_all} commits; {n_big} over {MAX_FILES} files dropped; {n_none} with no file of the snapshot; "
          f"{len(times)} kept, {len(files)} file changes; first {np.datetime64(int(times_a.min()), 's')}, last {np.datetime64(int(times_a.max()), 's')}")


if __name__ == "__main__":
    main()
