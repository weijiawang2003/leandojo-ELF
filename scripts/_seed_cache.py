"""Merge all existing baseline verification caches into a target cache file, so a
new eval reuses prior lean-cli results. Usage: python scripts/_seed_cache.py OUT.json"""
import glob
import json
import sys

merged = {}
for f in glob.glob("data/baselines/*/verification_cache.json") + ["/tmp/blind_probe_cache.json"]:
    try:
        merged.update(json.load(open(f)))
    except Exception:
        pass
out = sys.argv[1]
json.dump(merged, open(out, "w"))
print(f"seeded {len(merged)} cache entries into {out}")
