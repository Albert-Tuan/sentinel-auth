# M13 — Integration Handoff

> Sentinel Auth v3.3 · Milestone M13
> The integration plan for the two stacked pull requests, the evidence
> behind it, and the exact sequence to execute once the OWNER allows the
> merges.

This document is a **handoff note**, not a decision. Nothing in it has
been executed on the remote: neither PR has been merged, neither base has
been changed, and neither `dev` nor `main` has been touched.

---

## 1. The snapshot this plan was built on

| Ref | SHA | Notes |
|---|---|---|
| `origin/dev` | `377e8c88a2b68f619c5ddc7512bdb398c66ee6f1` | `Merge PR #20: Stitch-first M12 frontend integration` |
| PR #21 head | `dd352791807bcd1b9586220269d6b369b24840a3` | `feature/m13-demo-foundation` → `dev` |
| PR #22 head | `a0976f90f00cb9b62119d111ea8f85ca50380060` | `feature/m13-browser-e2e` → `feature/m13-demo-foundation` |
| code SHA (F1–F4 closed) | `0e4147d` | inside PR #22 |
| docs SHA | `a0976f9` | inside PR #22, acceptance matrix only |

**Reference CI run:** `46155280710` — 5/5 jobs green on `a0976f9`.

### 1.1 The ancestry

```
377e8c8  origin/dev  (Merge PR #20)
   │
   └─ dd35279  PR #21 head  (13 commits on top of dev)
         │
         └─ a0976f9  PR #22 head  (23 commits on top of PR #21)
```

* `git merge-base --is-ancestor origin/dev origin/feature/m13-demo-foundation` → **yes**.
* `git merge-base --is-ancestor origin/feature/m13-demo-foundation origin/feature/m13-browser-e2e` → **yes**.

The stack is clean: PR #21 sits directly on `dev`, and PR #22 sits
directly on PR #21. There is no divergence and no competing ancestor.

### 1.2 The repository settings

| Setting | Value |
|---|---|
| `allow_merge_commit` | `true` |
| `allow_squash_merge` | `true` |
| `allow_rebase_merge` | `true` |
| `allow_auto_merge` | `false` |
| Branch protection on `dev` | **none** (`404 Branch not protected`) |
| Required checks | **UNKNOWN** — no protection rule, so no required-check list exists to read |

### 1.3 The review state

| PR | Mergeable | Merge state | Reviews | Blocking comments |
|---|---|---|---|---|
| #21 | `MERGEABLE` | `CLEAN` | 2 × `COMMENTED` | none |
| #22 | `MERGEABLE` | `CLEAN` | 2 × `COMMENTED` | none |

`reviewDecision` is empty on both — no approval has been requested or
given, and nothing blocks the merge.

---

## 2. The integration plan

### 2.1 The recommended method: `--no-ff` merge commit

**Merge PR #21 into `dev` as a merge commit, then rebase PR #22 onto the
new `dev` and merge it as a merge commit as well.**

Why this method:

* It **preserves the ancestry**. PR #22's 23 commits stay on top of PR
  #21's 13 commits, exactly as they are today, so the history reads the
  way the work was actually done.
* It keeps the tree of the integration **identical to the tree CI has
  already verified** — see section 2.2.
* A merge commit on `dev` records the fact that two PRs were integrated,
  which a squash would erase.

The repository allows merge commits (`allow_merge_commit: true`), so
this method is available.

### 2.2 The evidence: the candidate tree is the verified tree

The integration was simulated on a throw-away branch
(`sim/m13-integration`, in a temporary worktree, `origin/dev` as its
base). The simulation ran **on the local machine only** — no remote ref
was changed, no PR was merged, and the branch was never pushed.

```
git worktree add /tmp/m13-integration-sim -b sim/m13-integration origin/dev
cd /tmp/m13-integration-sim
git merge --no-ff --no-edit dd352791807bcd1b9586220269d6b369b24840a3   # PR #21
git merge --no-ff --no-edit a0976f90f00cb9b62119d111ea8f85ca50380060   # PR #22
```

**Result: no conflict in either merge.**

| Tree | SHA |
|---|---|
| integration candidate (`sim/m13-integration`) | `b6223d4fcbcd83c62bb2a4bb6d8d01ba6c87bab7` |
| PR #22 head (`a0976f9`) | `b6223d4fcbcd83c62bb2a4bb6d8d01ba6c87bab7` |

```
git diff --stat a0976f90f00cb9b62119d111ea8f85ca50380060 HEAD
# (no output — the trees are identical)
```

**The candidate tree is byte-for-byte the tree that CI run `46155280710`
verified.** The integration introduces no change of its own, so there is
nothing new to regress and no reason to re-run the full regression suite.
The regression evidence already on record applies unchanged:

| Suite | Result | Provenance |
|---|---|---|
| Backend (pytest) | 1586 passed, 0 skipped | CI run `46155280710` |
| Frontend unit / integration | 265 / 50 | CI run `46155280710` |
| Browser E2E (Chromium) | 18 passed | CI run `46155280710` |
| Pre-token probe | 13 checks passed | CI run `46155280710` |
| HTTP smoke | 79 checks | CI run `46155280710` |

### 2.3 The alternatives, and why they are worse

**Squash PR #21, then merge PR #22.** Simulated on a separate
throw-away branch:

```
git merge --squash dd352791807bcd1b9586220269d6b369b24840a3 && git commit
git merge --no-ff --no-edit a0976f90f00cb9b62119d111ea8f85ca50380060
```

Result: **three `add/add` conflicts** — `docs/M13-ACCEPTANCE-MATRIX.md`,
`docs/M13-FULLSTACK-DEPLOYMENT.md` and `scripts/demo_stack.sh`.

The reason is structural, not accidental. Squashing PR #21 replaces its
tip SHA with a new commit, so the merge base between the squashed `dev`
and PR #22 falls back to `377e8c8` — the point where all three files did
not exist yet. Both sides now "add" the same path, and git cannot decide
which one wins. The conflict would have to be resolved by hand, and the
resolution would be a **judgement about three substantive files** — not a
mechanical merge.

**Squash PR #22 onto PR #21.** The same conflict, in the same three
files.

**Rebase PR #22 onto PR #21.** Simulated; it **succeeded cleanly** and
produced the **same tree** `b6223d4f`. It rewrites all 23 commits
though, so every commit gets a new SHA and the comparison against the
already-verified CI run becomes a diff between two histories rather than
a comparison between two trees. The merge-commit method reaches the same
tree with no rewrite and no ambiguity.

**Merge PR #22 directly onto `dev` without merging PR #21 first.**
Simulated; it also produced the same tree `b6223d4f`. It is *not*
recommended: it would put PR #22's changes on `dev` while leaving PR #21
unmerged, so `dev` would carry the browser suite and the probe without
the demo foundation they are written against. It also leaves PR #21
behind, still open, with a base that is now already contained in `dev`.

**Recommendation: the `--no-ff` merge commit, PR #21 first, then PR #22
re-based onto the new `dev`.**

---

## 3. The clean-checkout rehearsal

### 3.1 What was done

A **separate worktree** was created from the integration candidate, at
`/tmp/m13-rehearsal-clean`, checked out detached at the candidate commit
`2e56ecb`. Nothing was copied into it from the working environment: no
`.env`, no virtualenv, no `node_modules`, no configuration file.

The environment was created from the **template**, as the documentation
prescribes:

```bash
cp .env.demo.example .env.demo
# then: fresh POSTGRES_PASSWORD and INTERNAL_SECRET from `secrets.token_urlsafe`
# and the rehearsal's own ports / database names
```

The rehearsal used **its own compose project** (`sentinel-auth-m13-rehearsal`),
**its own ports** and **its own database names**:

| Component | Rehearsal | The operator's stack |
|---|---|---|
| PostgreSQL | `55460` | `55432` |
| Redis | `56390` | `56379` |
| API | `58010` | `58000` |
| Frontend | `55185` | `55173` |
| SMTP sink | `51035` | `51025` |
| Compose project | `sentinel-auth-m13-rehearsal` | `sentinel-auth-demo` |

The database names carried the `_demo` marker and the allowlist of
`scripts/e2e_fixtures_guard.py` was honoured
(`sentinel_core_demo`, `sentinel_detection_demo`, `sentinel_ml_demo`).

**The operator's running stack was not stopped, modified or reset.** The
operator's own PostgreSQL (`55432`) and Redis (`56379`) were already down
when the rehearsal started, and the rehearsal never touched them.

### 3.2 What was verified

| Step | Command | Result |
|---|---|---|
| start the stack | `scripts/demo_stack.sh start` | PostgreSQL healthy, three-database topology verified (13/7/3 tables), SMTP sink listening, API ready, frontend serving |
| seed | `scripts/demo_seed_demo.py --seed` | 4 users, 3 sessions, 3 device records; 5 alerts, 2 policies; 7 inference logs, 6 feature statistics |
| demo scenarios | `scripts/demo_scenarios.py --all` | **55 of 55 checks passed** |
| browser E2E | `scripts/e2e_run.sh --no-start` | **18 of 18 scenarios passed**, 0 skipped |
| pre-token probe | `scripts/demo_pre_token_probe.py` | **13 of 13 checks passed** |
| restart | `scripts/demo_stack.sh restart` | the stack came back up; the row counts were unchanged (`users=4 sessions=44 devices=4 alerts=14 attempts=70`) |
| acceptance command | `scripts/demo_stack.sh verify` | **55 of 55 checks passed** |

### 3.3 What was verified, and how

Three tiers, kept apart on purpose:

* **Automated** — the seed, the 55 demo scenario checks, the 18 browser
  E2E scenarios, the 13 pre-token probe checks, the restart-and-compare.
  Every number in the table above comes from a command that ran.
* **Manual** — the defence script in `docs/M13-DEFENSE-SCRIPT.md` is a
  10–15 minute **walk-through with a human narrating it**. It was
  **not** performed as a narrated live presentation in this rehearsal;
  the individual checks it depends on were run and passed
  individually. No claim is made here that a live, narrated
  presentation took place.
* **Read only** — `docs/M13-DEFENSE-SCRIPT.md` section 6 (the manual
  browser walk-through) and the questions reserved for the defence were
  read, not executed end to end.

### 3.4 The rehearsal found three real defects

The rehearsal was worth running: it surfaced three defects that the CI
suite does not cover, all of them in the **operating instructions**, not
in the product logic. All three are fixed in this round.

**Defect 1 — `scripts/demo_stack.sh verify` called a script that does not
exist.**

```python
python3 scripts/demo_verify.py
```

`scripts/demo_verify.py` was never committed to the repository. The
command was documented in `docs/M13-FULLSTACK-DEPLOYMENT.md` §3 and in
the script's own usage text, and it failed with
`No such file or directory`. **Fixed:** `verify` now runs the demo
scenarios, which *are* the demo's acceptance checks, and it exports the
environment the scenarios need.

**Defect 2 — `scripts/demo_scenarios.py` hard-coded the API port
`58000`.**

A rehearsal on non-default ports sent the scenarios to **another
stack's API** — in this case the operator's, which answered `500` for
every login. The scenario script also read `CORE_DATABASE_URL`,
`DETECTION_DATABASE_URL` and `INTERNAL_SECRET` from the **shell**, so a
stale exported variable could redirect its database writes and its
internal-boundary calls.

**Fixed:** the scenario script now reads `.env.demo` itself, and **the
file wins over the shell**. The API address comes from `CORE_APP_URL`
(and from `APP_HOST`/`APP_PORT`), so it can no longer drift onto a
hard-coded port.

**Defect 3 — `scripts/demo_seed_demo.py` read the database URLs from the
shell.**

With a stale `CORE_DATABASE_URL` still exported, the seed wrote its
fixtures into a **different stack's** databases than the ones the demo
was serving. The seed prints the targets it is about to write to, and
that line is what exposed it.

**Fixed:** the seed reads `.env.demo` itself, and the file wins over the
shell. The same rule now applies to the scenario script and to the
internal secret.

The documentation was corrected alongside the code:

* `docs/M13-FULLSTACK-DEPLOYMENT.md` §2.1 now installs the frontend
  dependencies **before** the first start — without them the start
  fails with
  `setsid: failed to execute ./node_modules/.bin/vite: No such file or directory`.
* §2.2 states that the environment **file** is the authority and that
  no `export`/`source` is needed.
* §2.4, §2.5 and the new §2.6 say the same for the seed, the scenarios
  and `verify`.
* §10.6 and §11 record the three symptoms with their fixes.

---

## 4. The product scope that is being handed over

| Workflow | Evidence that exists | Rehearsal result | Limits |
|---|---|---|---|
| Login / MFA / session / refresh / logout | 1586 backend tests; E2E-08 (4 race scenarios) | scenarios A, E2E-08 green | local demo stack only |
| Trusted device | 1586 backend tests; E2E-03 | scenario B green | one device per account in the fixtures |
| RBAC | 1586 backend tests; E2E-07 (3 scenarios) | scenario set green | four roles, no tenancy |
| Detection by rule | 1586 backend tests; probe | probe 13/13 green | rules are the demo's own; `critical` is reachable |
| Pre-token gate | probe; `scripts/demo_pre_token_probe.py` | RUN 1 `token=HELD`, RUN 2 `token=ISSUED` | two real logins per run |
| SOC investigation | 1586 backend tests; E2E-02, E2E-03, E2E-04 | scenarios C, D green | seeded alerts plus the ones the probe raises |
| Protective actions | 1586 backend tests; E2E-04 | scenario D 9/9 green | `REVOKE_SESSIONS` and `REQUIRE_MFA` |
| Policy lifecycle | 1586 backend tests; E2E-05 | scenario E green | one active policy at a time |
| Manager analytics / degraded behaviour | 1586 backend tests; E2E-06 (3 scenarios) | scenario F green | the ML source is degraded by design |

### 4.1 What is seeded, and what is real

**Seeded** — written by `scripts/demo_seed_demo.py`, deterministic and
idempotent:

* 4 users (`demo_user`, `demo_analyst`, `demo_admin`, `demo_manager`)
  with their roles, 3 sessions and 3 trusted-device records;
* 5 alerts and 2 policies in the detection context;
* 7 inference logs and 6 feature statistics in the ML context.

**Real** — produced by the run, not written by a fixture:

* every login, every MFA challenge and every session refresh;
* the two login attempts the pre-token probe makes, and the DETECTION
  scoring they trigger (`impossible_travel` + `multiple_failures`);
* the protective action that follows from the `critical` risk level;
* the alerts the pipeline raises for those attempts.

**The probe can create a `critical` alert and revoke the demo account's
sessions — and that is a legitimate protective action, not a leak.** The
Detection context asks Core to enforce `REVOKE_SESSIONS` through the
internal boundary; the revocation is the system working. The probe
restores the one-time MFA flag it found, and reports exactly what it
leaves behind.

**The ML model has not been promoted.** `ML_MODEL_PATH` is empty by
design, the analytics endpoints answer in degraded mode, and the
dashboard says `active_model_version=None`. No claim is made that any
model has reached a quality threshold.

**The scope is a local demo stack, and the browser is Chromium.** The
18 browser scenarios were exercised against Chromium only; no other
browser engine has been run.

**The rubric has not been checked against the original.** There is no
rubric document anywhere in the repository that states a scoring scheme
for the defence. This plan therefore does not add one, and it does not
add a public-deployment, load-test or ML requirement that the repository
does not already contain.

---

## 5. The known limitations, kept apart from the blockers

### 5.1 Blockers

**None.** There is no identified blocker to the integration.

### 5.2 Known limitations

| Limitation | What it means |
|---|---|
| The event-loop test is intermittent | `test_the_endpoint_does_not_block_the_event_loop_while_locked` failed in one CI run and passed on rerun; it also passed locally, ten times in a row. The root cause is **not confirmed**. The test and its threshold are unchanged. This is **not** a fixed bug, and the cause is **not** attributed to runner load — there is no evidence for that. |
| The browser suite is Chromium-only | no other engine has been exercised |
| The demo is local-only | no public deployment, no production data, no real users |
| The ML source is degraded | no promoted model; the analytics answer with the degraded envelope by design |
| The pre-token probe leaves real traffic behind | sessions, refresh tokens, MFA transactions and the two login attempts **remain**. The probe reports them; it does not hide them. |
| `verify` and the scenarios need the demo stack running | they are not standalone checks |
| The rehearsal used Podman, the CI used Docker | the container runtime differs; the compose overlay and the schema staging handle both |

---

## 6. The sequence to execute once the OWNER allows the merge

> This section is an **instruction for a future run**. None of it has
> been executed. No PR has been merged, no base has been changed, and
> `dev` and `main` are untouched.

**1. Verify that the refs have not moved.**

```bash
git fetch origin
git rev-parse origin/dev
git rev-parse origin/feature/m13-demo-foundation
git rev-parse origin/feature/m13-browser-e2e
```

Compare against §1. If any SHA differs, **stop** and re-run the
simulation of section 2.2 against the new tips before going on.

**2. Merge PR #21 with a merge commit.**

```bash
gh pr merge 21 --merge --repo Albert-Tuan/sentinel-auth
```

**3. Move PR #22's base to `dev`.**

```bash
gh pr edit 22 --base dev --repo Albert-Tuan/sentinel-auth
```

**4. Check the diff, the conflicts and the checks in the new state.**

```bash
gh pr view 22 --json baseRefName,mergeable,mergeStateStatus,statusCheckRollup
gh pr diff 22 --repo Albert-Tuan/sentinel-auth --name-only
```

The diff of PR #22 against the new `dev` must contain only PR #22's own
23 commits' worth of files — the browser suite, the probe, the fixture
guards and the M13 documentation. Anything from PR #21 appearing in that
diff would mean the base did not move as intended.

**5. Merge PR #22 only if every condition holds.**

* `mergeable` is `MERGEABLE`;
* `mergeStateStatus` is `CLEAN`;
* every status check is `SUCCESS`;
* the diff looks as described in step 4.

```bash
gh pr merge 22 --merge --repo Albert-Tuan/sentinel-auth
```

**6. Confirm the CI on `dev` and record the final integration SHA.**

```bash
gh run list --branch dev --limit 5
git rev-parse origin/dev
```

The final integration SHA — the commit `dev` points at after both merges
— is the SHA to record in the acceptance matrix.

**The local simulation in section 2.2 is not evidence that GitHub has
merged anything, and it is not evidence that the target branch's CI has
run.** Those are established by steps 2 to 6 and by nothing else.
