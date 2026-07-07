#!/usr/bin/env python3
"""Traceability & success-criteria gate.

Enforces the rules in WORKFLOW.md sections 5-6:

  1. Every spec file validates against schemas/spec.schema.json.
  2. Every requirement (REQ-xxx) declares >= 1 success_criteria and
     >= 1 validation_mechanism (required by the schema, re-checked here).
  3. Every requirement is referenced by at least one downstream generated
     artifact (via a '@traces REQ-xxx' annotation in generated/**).
  4. Every requirement has at least one validating test or llm_judge rubric
     entry, and every referenced test path / rubric id actually exists.
  5. The traceability manifest (eval/traceability.json), if present, is
     consistent with the specs on disk.

Exit code 0 = pass, 1 = one or more violations (blocks the gate).

Usage:
    python scripts/check_traceability.py                # full check
    python scripts/check_traceability.py --schema-only  # only schema validation
    python scripts/check_traceability.py --root .       # set repo root
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml  # pip install pyyaml
except ImportError:  # pragma: no cover
    print("ERROR: pyyaml is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

try:
    from jsonschema import Draft202012Validator  # pip install jsonschema
except ImportError:  # pragma: no cover
    print("ERROR: jsonschema is required (pip install jsonschema)", file=sys.stderr)
    sys.exit(2)


SPEC_DIR = "spec"
GENERATED_DIR = "generated"
TESTS_DIR = "tests"
EVAL_DIR = "eval"
SCHEMA_PATH = "schemas/spec.schema.json"
RUBRIC_PATH = "eval/rubric.jsonl"
MANIFEST_PATH = "eval/traceability.json"

REQ_ID_RE = re.compile(r"REQ-\d{3,}")
TRACES_RE = re.compile(r"@traces\s+(REQ-\d{3,})")


class Violations:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, msg: str) -> None:
        self.items.append(msg)

    def __bool__(self) -> bool:
        return bool(self.items)


def load_schema(root: Path) -> Draft202012Validator:
    schema_file = root / SCHEMA_PATH
    if not schema_file.exists():
        print(f"ERROR: schema not found at {schema_file}", file=sys.stderr)
        sys.exit(2)
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def load_specs(root: Path) -> list[tuple[Path, dict]]:
    spec_dir = root / SPEC_DIR
    specs: list[tuple[Path, dict]] = []
    if not spec_dir.exists():
        return specs
    for path in sorted(spec_dir.rglob("*.y*ml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            specs.append((path, {"__parse_error__": str(exc)}))
            continue
        if isinstance(data, dict):
            specs.append((path, data))
        else:
            specs.append((path, {"__parse_error__": "top-level YAML must be a mapping"}))
    return specs


def validate_schema(specs, validator, v: Violations) -> None:
    for path, data in specs:
        if "__parse_error__" in data:
            v.add(f"{path}: YAML parse error: {data['__parse_error__']}")
            continue
        errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
        for err in errors:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            v.add(f"{path}: schema violation at '{loc}': {err.message}")


def collect_traces(root: Path) -> set[str]:
    """REQ ids referenced by generated artifacts via '@traces REQ-xxx'."""
    traced: set[str] = set()
    gen_dir = root / GENERATED_DIR
    if not gen_dir.exists():
        return traced
    for path in gen_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        traced.update(TRACES_RE.findall(text))
    return traced


def load_rubric_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    rubric = root / RUBRIC_PATH
    if not rubric.exists():
        return ids
    for line in rubric.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = obj.get("id")
        if isinstance(rid, str):
            ids.add(rid)
    return ids


def check_traceability(root: Path, specs, v: Violations) -> None:
    traced = collect_traces(root)
    rubric_ids = load_rubric_ids(root)

    for path, data in specs:
        if "__parse_error__" in data:
            continue  # already reported
        req_id = data.get("id")
        if not req_id:
            continue  # schema stage reports missing id

        # Rule 3: downstream artifact reference.
        declared = data.get("downstream_artifacts") or []
        for art in declared:
            if not (root / art).exists():
                v.add(f"{path}: downstream artifact '{art}' does not exist")
        if req_id not in traced and not declared:
            v.add(
                f"{path}: {req_id} has no downstream artifact "
                f"(no '@traces {req_id}' annotation in {GENERATED_DIR}/ and no "
                f"downstream_artifacts entry)"
            )

        # Rule 4: at least one test/llm_judge validator, and refs must exist.
        mechanisms = data.get("validation_mechanism") or []
        has_auto = False
        for mech in mechanisms:
            mtype = mech.get("type")
            ref = mech.get("ref", "")
            if mtype in ("test", "check", "llm_judge"):
                has_auto = True
            if mtype == "test":
                if not (root / ref).exists():
                    v.add(f"{path}: {req_id} test ref '{ref}' does not exist")
            elif mtype == "llm_judge":
                if ref not in rubric_ids:
                    v.add(
                        f"{path}: {req_id} llm_judge ref '{ref}' not found in "
                        f"{RUBRIC_PATH}"
                    )
        if not has_auto:
            v.add(
                f"{path}: {req_id} has no automated validation mechanism "
                f"(need at least one of type test/check/llm_judge)"
            )


def check_manifest(root: Path, specs, v: Violations) -> None:
    manifest_file = root / MANIFEST_PATH
    if not manifest_file.exists():
        return  # optional
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        v.add(f"{MANIFEST_PATH}: invalid JSON: {exc}")
        return

    spec_ids = {d.get("id") for _, d in specs if "__parse_error__" not in d}
    manifest_ids = set(manifest.get("requirements", {}).keys())

    for missing in sorted(spec_ids - manifest_ids):
        if missing:
            v.add(f"{MANIFEST_PATH}: missing entry for {missing}")
    for stale in sorted(manifest_ids - spec_ids):
        v.add(f"{MANIFEST_PATH}: entry '{stale}' has no matching spec (stale)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Traceability & success-criteria gate.")
    parser.add_argument("--root", default=".", help="Repository root (default: .)")
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Only run JSON Schema validation of spec files.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    validator = load_schema(root)
    specs = load_specs(root)

    if not specs:
        print(f"No spec files found under {root / SPEC_DIR}/ — nothing to check.")
        return 0

    v = Violations()
    validate_schema(specs, validator, v)

    if not args.schema_only:
        # Only run traceability checks if schema passed for meaningful results.
        if not v:
            check_traceability(root, specs, v)
            check_manifest(root, specs, v)

    if v:
        print("Traceability gate FAILED:\n", file=sys.stderr)
        for item in v.items:
            print(f"  - {item}", file=sys.stderr)
        print(f"\n{len(v.items)} violation(s).", file=sys.stderr)
        return 1

    print(f"Traceability gate passed: {len(specs)} spec file(s) validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
