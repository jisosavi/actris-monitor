"""
The worked example on the documentation site must still match the real schema.

`docs/public/examples/get-series-response.json` was captured from the live
endpoint and is embedded verbatim into the *Connecting a client* page. That makes
it a second copy of the output shape — exactly the kind of hand-maintained
duplicate that `dump_mcp_tools.py` exists to prevent, and it would rot the first
time a field is added to `SeriesResult` with nobody noticing.

So it is validated here rather than trusted. These tests need no database and no
network: they parse a file and hand it to the model.

If one of these fails, the example is stale. Re-capture it against the deployed
endpoint rather than editing the JSON by hand — an invented example that passes
validation is worse than an honest one that failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.tools import SeriesResult  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent.parent / "docs" / "public" / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


def test_response_example_validates_against_the_model() -> None:
    """Every field the example carries is one the model still defines."""
    payload = _load("get-series-response.json")
    result = SeriesResult.model_validate(payload)

    # Round-trip: the model must not silently drop or rename anything.
    assert set(result.model_dump().keys()) == set(payload.keys())


def test_response_example_still_shows_a_gap() -> None:
    """The example earns its place by showing an explicit null, not just numbers.

    Gaps-as-explicit-nulls is the convention most likely to be misread by someone
    integrating, and this is the only place on the site a reader sees one.
    """
    rows = _load("get-series-response.json")["rows"]
    assert any(row["mean"] is None for row in rows), (
        "Re-captured example no longer contains a null mean — pick a station and "
        "range that still has a gap, or the example stops teaching the convention."
    )


def test_response_example_carries_full_provenance() -> None:
    """The provenance block is the reason to show a whole response rather than rows."""
    provenance = _load("get-series-response.json")["provenance"]
    assert set(provenance) == {
        "source", "qc_level", "mean_method", "coverage_basis", "citation",
    }
    assert all(str(v).strip() for v in provenance.values())


def test_request_example_matches_the_tool_signature() -> None:
    """The arguments shown are ones get_series actually accepts."""
    request = _load("get-series-request.json")
    assert request["method"] == "tools/call"
    assert request["params"]["name"] == "get_series"

    args = request["params"]["arguments"]
    import asyncio

    from mcp_server.server import mcp

    tool = next(
        t for t in asyncio.run(mcp.list_tools()) if t.name == "get_series"
    )
    schema = tool.input_schema or {}
    assert set(args) <= set(schema.get("properties", {})), "unknown argument in example"
    assert set(schema.get("required", [])) <= set(args), "example omits a required argument"

    allowed = schema["properties"]["variables"]["anyOf"][0]["items"]["enum"]
    assert set(args["variables"]) <= set(allowed)


@pytest.mark.parametrize("name", ["get-series-request.json", "get-series-response.json"])
def test_examples_are_formatted_for_embedding(name: str) -> None:
    """Indented and newline-terminated: they are read as code blocks, not parsed."""
    text = (EXAMPLES / name).read_text()
    assert text.endswith("\n")
    assert "\n  " in text, "example should be pretty-printed, not minified"
