#!/usr/bin/env bash
# Fresh full-day runs on GPU (MPS) and CPU for the 1 m and 0.5 m versions of one tile.
# Timings land in data/processed/<tile>/<device>/timing.json.
set -euo pipefail
cd "$(dirname "$0")/.."
for tile in 121500_485000 121500_485000_r0.5; do
  for dev in mps cpu; do
    uv run python scripts/run_solweig.py --tile "$tile" --date 2019-07-25 --device "$dev" --fresh \
      2>&1 | grep -E "^(mps|cpu):|Error|Traceback"
  done
done
