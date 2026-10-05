"""
export_openapi.py
-----------------
Exports the VishwAlpha FastAPI OpenAPI spec to openapi.json at the project root.
The frontend team can import this file directly into Postman.

Usage:
    uv run python export_openapi.py

The file is generated from the live app object (no server needed).
"""
import json
from pathlib import Path

from app.main import app

spec = app.openapi()

out = Path(__file__).parent / "openapi.json"
out.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"[OK] OpenAPI spec written to: {out}")
print(f"     Title   : {spec.get('info', {}).get('title')}")
print(f"     Version : {spec.get('info', {}).get('version')}")
print(f"     Paths   : {len(spec.get('paths', {}))}")
print()
print("Import openapi.json into Postman:")
print("  File -> Import -> select openapi.json")
print("  Or: npx openapi-to-postmanv2 convert -s openapi.json -o postman_collection.json")
