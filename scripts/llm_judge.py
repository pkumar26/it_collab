#!/usr/bin/env python3
"""LLM-as-a-judge evaluation gate.

Implements the rubric-based, deterministic, ensemble judge described in
CONTRIBUTING.md section 6.2:

  * Loads each requirement spec (spec/**.yaml) and its declared success_criteria.
  * Loads matching rubric entries from eval/rubric.jsonl.
  * Loads the downstream artifact(s) under review (via '@traces REQ-xxx' or the
    spec's downstream_artifacts).
  * Runs a rubric-based prompt at temperature 0, N times (ensemble), and takes a
    majority vote per criterion to reduce variance.
  * Writes a machine-readable verdict JSON (per-criterion pass/fail/needs-review
    + cited justification + pinned model version + run metadata).
  * Exits non-zero if any criterion fails, or if any lands in 'needs-review'
    without a human sign-off marker present.

The actual model call is isolated in `call_model()`. By default this script runs
in OFFLINE mode (no network) using a deterministic heuristic so the pipeline is
runnable end-to-end without credentials. Set LLM_API_KEY + LLM_ENDPOINT and
implement/enable the real call to use a live model.

Exit codes: 0 = all pass, 1 = at least one fail/needs-review, 2 = config error.

Usage:
    python scripts/llm_judge.py --root . --out eval/results/verdict.json
    python scripts/llm_judge.py --root . --all --samples 3 --model gpt-judge-2025-12
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml  # pip install pyyaml
except ImportError:  # pragma: no cover
    print("ERROR: pyyaml is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

SPEC_DIR = "spec"
GENERATED_DIR = "generated"
RUBRIC_PATH = "eval/rubric.jsonl"
SIGNOFF_PATH = "eval/human-signoff.json"

TRACES_RE = re.compile(r"@traces\s+(REQ-\d{3,})")
VERDICTS = ("pass", "fail", "needs-review")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_specs(root: Path) -> list[dict]:
    specs: list[dict] = []
    spec_dir = root / SPEC_DIR
    if not spec_dir.exists():
        return specs
    for path in sorted(spec_dir.rglob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("id"):
            data["__path__"] = str(path.relative_to(root))
            specs.append(data)
    return specs


def load_rubric(root: Path) -> dict[str, dict]:
    rubric: dict[str, dict] = {}
    path = root / RUBRIC_PATH
    if not path.exists():
        return rubric
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict) and obj.get("id"):
            rubric[obj["id"]] = obj
    return rubric


def resolve_artifacts(root: Path, spec: dict) -> list[Path]:
    paths: list[Path] = []
    for art in spec.get("downstream_artifacts") or []:
        p = root / art
        if p.exists():
            paths.append(p)
    # Also include generated files that @trace this requirement.
    req_id = spec["id"]
    gen_dir = root / GENERATED_DIR
    if gen_dir.exists():
        for p in gen_dir.rglob("*"):
            if p.is_file():
                try:
                    if req_id in TRACES_RE.findall(
                        p.read_text(encoding="utf-8", errors="ignore")
                    ):
                        if p not in paths:
                            paths.append(p)
                except OSError:
                    continue
    return paths


def load_signoffs(root: Path) -> set[str]:
    """REQ ids that have an explicit human sign-off for needs-review cases."""
    path = root / SIGNOFF_PATH
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {k for k, v in data.get("approved", {}).items() if v}


# --------------------------------------------------------------------------- #
# The model call
# --------------------------------------------------------------------------- #
def build_prompt(spec: dict, criterion: dict, artifact_text: str, rubric: dict) -> str:
    """Rubric-based, structured prompt. Returned for auditability."""
    guidance = ""
    if rubric:
        guidance = json.dumps(rubric.get("checks", rubric), ensure_ascii=False)
    return (
        "You are a strict acceptance judge. Given a requirement, ONE success "
        "criterion, optional rubric guidance, and the artifact under review, "
        "decide whether the artifact satisfies the criterion.\n"
        "Respond ONLY with compact JSON: "
        '{\"verdict\": \"pass|fail|needs-review\", \"justification\": \"...\"}.\n'
        "Cite concrete evidence from the artifact in the justification.\n\n"
        f"REQUIREMENT {spec['id']}: {spec.get('title','')}\n"
        f"DESCRIPTION: {spec.get('description','')}\n"
        f"CRITERION {criterion.get('id')}: {criterion.get('statement')}\n"
        f"MEASURE: {criterion.get('measure','(none)')}\n"
        f"RUBRIC: {guidance or '(none)'}\n\n"
        f"ARTIFACT:\n{artifact_text[:6000]}\n"
    )


def call_model(prompt: str, model: str) -> dict:
    """Return {'verdict': ..., 'justification': ...}.

    OFFLINE default: deterministic heuristic so the pipeline runs without
    credentials. Replace the body below with a real client call (temperature 0)
    when LLM_API_KEY + LLM_ENDPOINT are set.
    """
    api_key = os.environ.get("LLM_API_KEY")
    endpoint = os.environ.get("LLM_ENDPOINT")

    if api_key and endpoint:
        # ---- Real model call goes here -------------------------------------
        # Example (pseudocode — wire to your provider SDK, temperature=0):
        #
        #   import requests
        #   resp = requests.post(
        #       endpoint,
        #       headers={"Authorization": f"Bearer {api_key}"},
        #       json={"model": model, "temperature": 0,
        #             "messages": [{"role": "user", "content": prompt}]},
        #       timeout=60,
        #   )
        #   content = resp.json()["choices"][0]["message"]["content"]
        #   return json.loads(content)
        #
        raise NotImplementedError(
            "Live LLM judging is not wired up. Implement call_model() for your "
            "provider, or unset LLM_API_KEY/LLM_ENDPOINT to use offline mode."
        )

    # ---- OFFLINE deterministic heuristic -----------------------------------
    # Extract the criterion line and check the artifact mentions its key tokens.
    m = re.search(r"CRITERION [^:]+:\s*(.+)", prompt)
    criterion = (m.group(1) if m else "").lower()
    artifact = prompt.split("ARTIFACT:\n", 1)[-1].lower()
    tokens = [t for t in re.findall(r"[a-z_]{4,}", criterion)]
    if not tokens:
        return {"verdict": "needs-review", "justification": "No tokens to match."}
    hits = sum(1 for t in tokens if t in artifact)
    ratio = hits / len(tokens)
    if ratio >= 0.6:
        return {
            "verdict": "pass",
            "justification": f"Artifact references {hits}/{len(tokens)} key terms.",
        }
    if ratio == 0:
        return {
            "verdict": "fail",
            "justification": "Artifact references none of the criterion terms.",
        }
    return {
        "verdict": "needs-review",
        "justification": f"Partial match ({hits}/{len(tokens)} terms).",
    }


def majority_verdict(samples: list[dict]) -> dict:
    counts = Counter(s["verdict"] for s in samples)
    # Bias toward caution: any fail majority => fail; ties => needs-review.
    top, n = counts.most_common(1)[0]
    if list(counts.values()).count(n) > 1:
        winner = "needs-review"
    else:
        winner = top if top in VERDICTS else "needs-review"
    justification = next(
        (s["justification"] for s in samples if s["verdict"] == winner),
        samples[0]["justification"],
    )
    return {
        "verdict": winner,
        "justification": justification,
        "distribution": dict(counts),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def evaluate(root: Path, samples: int, model: str, only_id: str | None) -> dict:
    specs = load_specs(root)
    rubric = load_rubric(root)
    signoffs = load_signoffs(root)

    results: list[dict] = []
    for spec in specs:
        if only_id and spec["id"] != only_id:
            continue
        artifacts = resolve_artifacts(root, spec)
        artifact_text = "\n\n".join(
            f"# FILE: {p}\n{p.read_text(encoding='utf-8', errors='ignore')}"
            for p in artifacts
        ) or "(no artifact found)"
        req_rubric = rubric.get(spec["id"], {})

        criteria_results = []
        for criterion in spec.get("success_criteria", []):
            prompt = build_prompt(spec, criterion, artifact_text, req_rubric)
            votes = [call_model(prompt, model) for _ in range(max(1, samples))]
            decision = majority_verdict(votes)
            criteria_results.append(
                {
                    "criterion_id": criterion.get("id"),
                    "statement": criterion.get("statement"),
                    **decision,
                }
            )

        req_verdict = "pass"
        if any(c["verdict"] == "fail" for c in criteria_results):
            req_verdict = "fail"
        elif any(c["verdict"] == "needs-review" for c in criteria_results):
            req_verdict = "needs-review"

        # A signed-off requirement downgrades needs-review to pass.
        if req_verdict == "needs-review" and spec["id"] in signoffs:
            req_verdict = "pass"

        results.append(
            {
                "id": spec["id"],
                "spec": spec.get("__path__"),
                "artifacts": [str(p.relative_to(root)) for p in artifacts],
                "verdict": req_verdict,
                "criteria": criteria_results,
            }
        )

    overall = "pass"
    if any(r["verdict"] == "fail" for r in results):
        overall = "fail"
    elif any(r["verdict"] == "needs-review" for r in results):
        overall = "needs-review"

    return {
        "overall": overall,
        "model": model,
        "samples": samples,
        "offline_mode": not (os.environ.get("LLM_API_KEY") and os.environ.get("LLM_ENDPOINT")),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requirements": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-as-a-judge acceptance gate.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="eval/results/verdict.json")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "offline-judge"))
    parser.add_argument("--all", action="store_true", help="Evaluate all requirements.")
    parser.add_argument("--id", default=None, help="Evaluate only this REQ id.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    only_id = None if args.all else args.id

    verdict = evaluate(root, args.samples, args.model, only_id)

    out_path = root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(verdict, indent=2), encoding="utf-8")

    print(f"LLM judge overall verdict: {verdict['overall'].upper()}")
    print(f"Verdict written to {out_path}")
    for r in verdict["requirements"]:
        print(f"  {r['id']}: {r['verdict']}")

    return 0 if verdict["overall"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
