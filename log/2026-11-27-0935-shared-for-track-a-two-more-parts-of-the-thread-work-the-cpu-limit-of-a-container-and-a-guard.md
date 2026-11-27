# For track A: two more parts of the thread work, if you can take them overnight. The CPU limit of a container, and a guard that keeps the slowdown from coming back

- **Track:** shared: from track C's session, for track A. It adds to our entry of 09:25 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 09:35 UTC
- **Work package:** C2 (the compact index) and C6 (what codemem costs on a machine)
- **Branch, commits, pull request:** `andre/compact-threads` (the script is at `532d188`; more commits follow tonight: a `--check` flag, a paragraph in `docs/plan/track-c-memory.md`, and two candidate fixes)

## Done

**Andre's aim, in one sentence:** a user installs codemem and never thinks about threads; codemem sets them, as `auto` sets the index. The work has three parts. Part 1 is the entry of 09:25 UTC (one query on one thread, a build on the cores). This entry is parts 2 and 3. **Andre asks you to take them if you can; if you cannot, say so, and they stay in the plan as proposals** (they are written there, §4.2, so that we check at the end what was done).

**The order that suits your queue.** Nothing here may hold up the hard tier or the runs.

1. The first run of the script, in the quiet window after the ruff group (your step 3). It names the pool.
2. The fix of part 1, measured in the next quiet gap between build groups. A timing needs the PC quiet for 2 to 4 minutes; the rest (reading, changing, testing) can go on beside your builds.
3. Parts 2 and 3 below, beside the builds: they need no quiet machine, only one container.

**Part 2: codemem reads the CPUs its process may use.**

- **The fault it removes.** In a container that is allowed 4 CPUs on a 16-CPU host, Python, FAISS, numpy and torch all see 16 and start 16 threads each (your own comment in `e2e_run.py`: "Python in a container sees all processors of the host, also with --cpus"). Your runner works around it by setting `OMP_NUM_THREADS` to the container's CPUs. A user's container has nobody to do that.
- **What to build.** Beside `physical_memory()` in `src/codemem/config.py`, which already reads the container's memory limit (`/sys/fs/cgroup/memory.max`), a function that returns the CPUs this process may use: the smaller of the affinity mask (`os.sched_getaffinity(0)`, where it exists) and the cgroup's quota (version 2: `/sys/fs/cgroup/cpu.max`, "quota period" or "max period"; version 1: `cpu.cfs_quota_us` over `cpu.cfs_period_us`, -1 for no limit), rounded up, at least 1.
- **Where it acts.** At import (`src/codemem/__init__.py`, before FAISS, numpy or torch is loaded), and only when that number is smaller than `os.cpu_count()`: it sets `OMP_NUM_THREADS` and `OPENBLAS_NUM_THREADS` to it with `setdefault`, so a value the user set wins. On a machine with no limit nothing changes. Whatever goes wrong while reading, nothing is set and nothing is raised: this code runs in every codemem process.
- **Done when:** unit tests with made-up cgroup files and a made-up affinity mask pass (a quota of 400000 100000 gives 4; "max" gives no limit; a quota of 150000 100000 gives 2; a user's `OMP_NUM_THREADS=8` stays 8; an unreadable file changes nothing); and on your PC `docker run --cpus 4 ...` with nothing set prints 4 for `faiss.omp_get_max_threads()` after `import codemem`, and 16 outside a container.
- **It does not change your runs:** the runner sets the variables already, and `setdefault` leaves them.

**Part 3: a guard.** `scripts/time_compact_search.py --check` (the flag arrives on the branch tonight): the script exits with status 1 and one line of reason when a compact search on all cores is more than 15% and more than 2 ms slower than on one thread, or when two thread settings return different results. It is run by hand on a quiet machine, like `scripts/check_faiss_calls.py`; it is not a pytest test. **What we need from you:** after the fix, run it with `--check` on the PC and say whether those two thresholds are sound there or too tight for the noise of your machine.

**The fix and both parts come back as one pull request** from your branch (or as changes on `andre/compact-threads`, as you prefer), with the tables before and after. Andre reviews and merges. Nothing of this is merged on our side tonight.

## Checked

- The facts about codemem's code were read at `463171c`: `physical_memory()` and `_CGROUP_LIMITS` in `config.py`; the macOS guard in `__init__.py` (it uses the same `setdefault` for `KMP_DUPLICATE_LIB_OK`); your runner's two variables in `e2e_run.py`.
- Not checked: any of it in a container. That is why it is asked of you.

## Left

- On our side: the `--check` flag, the plan's paragraph and the two candidate fixes on `andre/compact-threads`, tonight.

## Blocked on, or needed from others

- **Track A:** the script's first output; then, as the queue allows, the fix by the goals of 09:25 UTC, and parts 2 and 3. If a part does not fit before the runs, one line saying so.

## Next

- Andre's session reads your table when it is posted, and pushes the remaining commits to the branch.
