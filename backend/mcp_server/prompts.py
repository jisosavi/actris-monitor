"""
Prompts: message templates the *user* picks from a menu in their client — a slash
command in Claude Code, an item under Connectors in Claude Desktop's composer.

They exist to encode the analyses we already know how to do properly, including
the caveats a model will not apply unprompted. That is the whole point: this
dataset is easy to misreport, and a prompt is the one place where "say which years
are missing" can be made non-optional.

Only one prompt lives here so far, because the rest of the planned set
(`station_trend_report`, `network_comparison`, `anomaly_check`) needs tools that
do not exist yet. Their specifications are in `docs/mcp-server-plan.md` — written
before the tools deliberately, because a prompt's checklist is a requirements
document for the tools it calls.

Same import discipline as `tools.py`: no FastAPI, no MCP SDK. Registration lives
in `server.py`.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field


def data_availability_briefing(
    variable: Annotated[
        str,
        Field(
            description=(
                "Restrict the briefing to one variable: N, scattering or absorption. "
                "Leave blank to cover all three."
            )
        ),
    ] = "",
) -> str:
    """Summarise what data this server holds, and where the gaps are.

    Use this before planning any analysis. It reports the available periods per
    variable, names the gaps rather than glossing over them, and states the
    data-quality caveats that apply to every number this server returns.
    """
    scope = (
        f"Restrict the briefing to the '{variable}' variable."
        if variable
        else "Cover all three variables."
    )

    return f"""\
Call the `get_coverage` tool, then brief me on what data is available. {scope}

Report, in this order:

1. **What exists** — for each variable, the span of periods held and how many
   stations report in a typical period. Use the units and wavelengths from the
   response, not from your own knowledge.
2. **Where the gaps are** — name any period inside the overall span that is
   missing, and any period present but reporting zero stations. A period reporting
   zero stations is not the same as a period that was never fetched, and the
   difference matters: say which it is. Do not describe coverage as complete
   without checking every period in the range.
3. **What the caveats mean for me** — read the `provenance` block and restate, in
   your own words, what `coverage_basis` and `mean_method` imply for the analyses
   I might attempt. Specifically: that a station-year says nothing about how much
   of the year was observed, and that a station's annual mean is an unweighted
   average across however many files it submitted.
4. **What I should not ask for** — this server holds annual means only. If an
   analysis needs monthly, daily or hourly figures, say so plainly instead of
   approximating from annual values.

Do not fetch anything else, do not estimate values, and do not fill gaps with
interpolation. If `get_coverage` reports no data at all, say that and stop — no
retry will help, because this server never fetches on demand.
"""
