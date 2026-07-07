# it_collab

A repository template for a **milestone-gated AI development pipeline**: a
milestone-based Git workflow with automated quality gates — deterministic checks
plus **LLM-as-a-judge** evaluation — so that specifications and AI-generated code
are only accepted when they pass defined, **traceable** success criteria.

Every requirement gets a stable ID (e.g. `REQ-014`) that is threaded through its
spec, generated code, tests, and judge rubric. This makes requirement changes
scoped and auditable: change a requirement and the gates know exactly what to
re-evaluate.

## Why

- **One source of truth** — `main` is always buildable; use branches and tags, not
  parallel repo copies.
- **Reproducible regeneration** — only artifacts tracing a changed requirement are
  rebuilt, with a pinned generator version.
- **Controlled rollback** — milestones are annotated tags; roll back to the last
  tag whose gates passed.
- **Automated quality gates** — cheap deterministic checks run first, then an LLM
  judge covers semantic correctness that tests can't assess.

## How it fits together

```
spec/REQ-014.yaml ──► success_criteria + validation_mechanism (REQUIRED by schema)
        │
        ├─► generated/create_user.js       // @traces REQ-014
        ├─► tests/req_014_validation.test.js
        └─► eval/rubric.jsonl               { "id": "REQ-014", "checks": [...] }
                    │
                    ▼
        eval/traceability.json  (manifest: REQ → validators → artifacts)
```

Gates run cheap → expensive: pre-commit hygiene → deterministic gates
(schema, traceability, build, tests, secrets) → LLM-as-judge → human sign-off →
milestone acceptance evaluation on tag.

## Repository layout

| Path | What it is |
|------|------------|
| [PIPELINE_README.md](PIPELINE_README.md) | Full pipeline guide: how the pieces fit and how to run them |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Git branching strategy, milestones, gates, rollback, anti-patterns |
| [schemas/spec.schema.json](schemas/spec.schema.json) | JSON Schema requiring `success_criteria` + `validation_mechanism` per requirement |
| [scripts/check_traceability.py](scripts/check_traceability.py) | Deterministic gate: schema + REQ → artifact → validator traceability |
| [scripts/llm_judge.py](scripts/llm_judge.py) | LLM-as-a-judge gate (ensemble, rubric-based, offline fallback) |
| [spec/REQ-014.yaml](spec/REQ-014.yaml) | Example requirement specification |
| [eval/rubric.jsonl](eval/rubric.jsonl) | Example judge rubric entry |
| [eval/traceability.json](eval/traceability.json) | Traceability manifest (REQ → validators → artifacts) |
| [eval/results/verdict.json](eval/results/verdict.json) | Machine-readable judge verdict output |
| [generated/create_user.js](generated/create_user.js) | Example generated artifact (`@traces REQ-014`) |
| [tests/req_014_validation.test.js](tests/req_014_validation.test.js) | Example validating tests |

## Prerequisites

- **Python 3.12+** with `pyyaml` and `jsonschema` (and optionally `pre-commit`):
  ```bash
  pip install pyyaml jsonschema pre-commit
  ```
- **Node.js 18+** for the example tests (swap in your own stack's runner).

## Quick start

From the repository root:

```bash
# 1. Deterministic gate: validate specs + traceability
python scripts/check_traceability.py --root .

# 2. LLM-as-judge gate (offline mode by default — no credentials needed)
python scripts/llm_judge.py --root . --all --samples 3

# 3. Run the example tests
node --test tests/req_014_validation.test.js
```

Expected output:

```
Traceability gate passed: 1 spec file(s) validated.
LLM judge overall verdict: PASS
  REQ-014: pass
# pass 3  # fail 0
```

The judge writes a per-criterion verdict (pass/fail + justification + model + run
metadata) to [eval/results/verdict.json](eval/results/verdict.json) for audit.

## Add a new requirement

1. Write the spec in `spec/REQ-XXX.yaml` — the schema **requires** `id`, `title`,
   `description`, `status`, at least one `success_criteria` (`AC-x`) item, and at
   least one `validation_mechanism` (`test` / `check` / `llm_judge`).
2. Generate/write the artifact in `generated/` with a `// @traces REQ-XXX` comment.
3. Add validating tests at the path named in `validation_mechanism.ref`.
4. (Optional) Add a judge rubric line to `eval/rubric.jsonl` keyed by the REQ id.
5. Update the manifest `eval/traceability.json` (or let CI flag it).
6. Run the gates locally before opening a PR.

## Local Git hooks

Local hooks give fast, **bypassable** feedback before a commit lands. They are
**defined** in [.pre-commit-config.yaml](.pre-commit-config.yaml) but only become
active Git hooks after you install them.

### 1. Where they're defined

[.pre-commit-config.yaml](.pre-commit-config.yaml) at the repo root. The
project-specific gates are in the `repo: local` section:

- `spec-schema-validate` → runs `python scripts/check_traceability.py --schema-only`
- `traceability-check` → runs `python scripts/check_traceability.py`

Plus third-party hooks above them: whitespace/YAML/JSON hygiene, `gitleaks` secret
scanning, `ruff` (Python lint/format), and `prettier` (JS/TS/JSON/MD/YAML format).

### 2. Where they run from (after install)

The config file is **not** a hook by itself — you have to activate it:

```bash
cd <your-repo>
pip install pre-commit   # or: pipx install pre-commit
pre-commit install
```

That command writes an executable hook script to `.git/hooks/pre-commit`. From then
on, every `git commit` triggers `.git/hooks/pre-commit`, which invokes the
`pre-commit` tool, which reads [.pre-commit-config.yaml](.pre-commit-config.yaml)
and runs each defined hook against your staged files.

Run the hooks manually, without committing:

```bash
pre-commit run --all-files
```

### Important caveats

- **Nothing exists in `.git/hooks/` until you run `pre-commit install`** — until
  then only the *definition* file exists.
- **`.git/hooks/` is not committed** — it lives inside each clone's `.git/` folder,
  so every contributor must run `pre-commit install` once.
- **Local hooks are bypassable** (`git commit --no-verify`), which is why the same
  checks are duplicated as **required status checks** in CI (see below). That CI
  layer is the authoritative gate.

## CI enforcement

The authoritative enforcement is CI plus branch protection — the deterministic
gates, the LLM-judge job, and the milestone-acceptance evaluation are required
status checks that cannot be bypassed.

See [PIPELINE_README.md](PIPELINE_README.md) for CI/branch protection setup,
offline vs. live judge modes, and customizing for your stack.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the full branching, milestone, and
regeneration/rollback policy.