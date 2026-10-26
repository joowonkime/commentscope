"""Run offline Factory contract checks; no model inference or quality scoring."""
import argparse
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "test_scope_reference_review",
    "test_minimal_pipeline",
    "test_minimal_agents",
    "test_comment_utilization",
    "test_acceptance_r5",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    (ROOT / "runs").mkdir(exist_ok=True)
    for path in (ROOT, ROOT / "tests", ROOT / "src"):
        sys.path.insert(0, str(path))
    print("Offline checks: synthetic sources and scripted model responses.", flush=True)
    print("No Qwen, GPU, network, or API key is used.", flush=True)
    print("Passing confirms tested contracts, not real clustering quality.", flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
