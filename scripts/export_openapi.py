"""Write the API contract as JSON without a running server (verification.md §2.4).

    cd backend && uv run --no-sync python ../scripts/export_openapi.py [out.json]   # default: ../frontend/openapi.json

Then in frontend/: `npx openapi-typescript openapi.json -o src/api/schema.gen.ts`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from riskminer.api.main import app

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "frontend" / "openapi.json"
spec = app.openapi()
out.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"{out}: {len(spec['paths'])} paths")
