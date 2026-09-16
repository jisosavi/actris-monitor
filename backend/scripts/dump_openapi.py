#!/usr/bin/env python3
"""
Generate `docs/openapi.json` — the public REST surface, and only that.

A sibling of `dump_mcp_tools.py` on purpose: same shape, same `--check` flag, same
rule that the generated file is never hand-edited. One more artefact under an
existing convention is cheap; a second, different convention is not.

Why a filtered copy rather than the app's own `/openapi.json`:

  Every route carries exactly one tag — Public, Admin or Internal. This script
  keeps the Public ones and drops the rest, so the published reference cannot
  advertise `/api/db/reset` or a debug endpoint that reaches out to NILU. The
  alternative, `include_in_schema=False` on those routes, would also hide them
  from the app's own /docs — and the operator running a fetch is exactly who
  needs them there.

  It also means the documentation site serves a static file it can verify, rather
  than depending on the deployed backend being reachable at build time.

    python scripts/dump_openapi.py            # write docs/openapi.json
    python scripts/dump_openapi.py --check    # exit 1 if the file is stale

Run it after adding, retagging or re-describing a route.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from main import app  # noqa: E402  (needs the path above)

OUTPUT = _BACKEND.parent / "docs" / "public" / "openapi.json"

PUBLISHED_TAG = "Public"

SERVERS = [
    {
        "url": "https://actris-monitor-production.up.railway.app",
        "description": "Production",
    }
]

DESCRIPTION = """\
The read-only HTTP surface behind the [ACTRIS Monitor dashboard](https://www.isosavi.com/test/actris-monitor/).

Annual-mean in-situ aerosol measurements from the EBAS/ACTRIS European research
network — three variables, Level 2 quality-assured only, 2000 onwards. Responses
are served from this service's own database; no request here reaches NILU.

**Data is annual.** One mean per station, variable and calendar year. Monthly or
daily figures do not exist and cannot be derived from these endpoints.

**Two caveats the numbers do not carry.** A station-year's mean is unweighted
across that station's files and may mix size cuts, so a step between years can
come from a file appearing rather than from the atmosphere. And no field states
what fraction of a year was actually observed — `data_coverage` is a has-data
flag despite its name. Both are explained in the
[design notes](https://www.isosavi.com/test/actris-monitor/docs/mcp-server-plan.html).

**Please cite the data.** Measurements are contributed by station principal
investigators; acknowledge them and EBAS/ACTRIS in any published use.

Agents are better served by the [MCP endpoint](https://www.isosavi.com/test/actris-monitor/docs/mcp-reference.html),
which carries provenance on every response.

This document is generated from the running application by
`backend/scripts/dump_openapi.py` and lists only the endpoints tagged `Public`.
Administrative and internal routes exist and are deliberately absent.
"""


def _refs(node: Any, found: set[str]) -> None:
    """Collect every `#/components/schemas/X` reachable from `node`."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _refs(value, found)
    elif isinstance(node, list):
        for item in node:
            _refs(item, found)


def build() -> str:
    spec: dict[str, Any] = app.openapi()

    # Keep only Public operations, and drop any path left with none.
    paths: dict[str, Any] = {}
    for path, item in spec.get("paths", {}).items():
        kept = {
            method: op
            for method, op in item.items()
            if isinstance(op, dict) and PUBLISHED_TAG in (op.get("tags") or [])
        }
        if not kept:
            continue
        # The published document is public by construction, so a lone "Public"
        # group heading would be noise to a reader. Drop the tag itself.
        for op in kept.values():
            op.pop("tags", None)
        paths[path] = kept

    spec["paths"] = paths
    spec.pop("tags", None)

    # Schemas are transitively reachable; a component referenced only by a dropped
    # admin route would otherwise linger (FetchRequest is the current example).
    reachable: set[str] = set()
    _refs(paths, reachable)
    while True:
        grown = set(reachable)
        for name in list(reachable):
            _refs(spec.get("components", {}).get("schemas", {}).get(name, {}), grown)
        if grown == reachable:
            break
        reachable = grown

    schemas = spec.get("components", {}).get("schemas", {})
    kept_schemas = {k: v for k, v in schemas.items() if k in reachable}
    if kept_schemas:
        spec["components"]["schemas"] = kept_schemas
    else:
        spec.get("components", {}).pop("schemas", None)
        if not spec.get("components"):
            spec.pop("components", None)

    spec["info"]["description"] = DESCRIPTION
    spec["servers"] = SERVERS
    # JSON has no comments, so the "do not hand-edit" banner has to be a field.
    spec["info"]["x-generated-by"] = "backend/scripts/dump_openapi.py — do not edit by hand"

    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    content = build()
    rel = OUTPUT.relative_to(_BACKEND.parent)

    if "--check" in sys.argv:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        if current != content:
            print(
                f"{rel} is out of date. "
                "Regenerate with: cd backend && python scripts/dump_openapi.py",
                file=sys.stderr,
            )
            return 1
        print(f"{rel} is up to date.")
        return 0

    OUTPUT.write_text(content)
    n = len(json.loads(content)["paths"])
    print(f"Wrote {rel} ({len(content)} bytes, {n} public paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
