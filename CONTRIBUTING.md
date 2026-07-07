# Contributing

Thanks for contributing! The full development process — Git branching strategy,
milestones, quality gates, regeneration, and rollback policy — lives in
**[WORKFLOW.md](WORKFLOW.md)**. Read it before opening a pull request.

## Quick start

1. Branch from `main`: `git checkout -b feature/REQ-XXX-short-desc`.
2. Install local hooks once: `pip install pre-commit && pre-commit install`.
3. Make small, focused commits. Hooks run automatically on commit.
4. Run the gates locally before pushing:
   ```bash
   python scripts/check_traceability.py --root .
   python scripts/llm_judge.py --root . --all --samples 3
   ```
5. Open a PR to `main`. All required status checks (deterministic gates,
   LLM-judge, traceability) plus a human review must pass before merge.

See **[WORKFLOW.md](WORKFLOW.md)** for branch types, milestone tagging, the gate
architecture, and the anti-patterns to avoid. See
[PIPELINE_README.md](PIPELINE_README.md) for how to run and customize the pipeline.
