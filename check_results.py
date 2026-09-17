"""Score faxes_out/worklist.csv against expected.json. Run: python check_results.py"""
import csv
import json
import sys
from pathlib import Path

out_dir = sys.argv[1] if len(sys.argv) > 1 else "faxes_out"
expected = json.loads(Path("expected.json").read_text())
rows = {r["fax"]: r for r in csv.DictReader(open(f"{out_dir}/worklist.csv", encoding="utf-8"))}

checked = wrong = 0
for fax, want in expected.items():
    got = rows.get(fax)
    if got is None:
        print(f"{fax}: MISSING from worklist")
        wrong += len(want)
        checked += len(want)
        continue
    for key, val in want.items():
        checked += 1
        if (got.get(key) or "") != val:
            wrong += 1
            print(f"{fax}: {key}: got {got.get(key)!r}, want {val!r}")

print(f"\n{checked - wrong}/{checked} fields correct across {len(expected)} faxes")
sys.exit(1 if wrong else 0)
