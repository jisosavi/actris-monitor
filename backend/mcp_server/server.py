"""
The MCP server instance, its tool registration, and the ASGI app `main.py` mounts.

Registration lives here rather than as decorators in `tools.py` so that the tool
implementations never import the MCP SDK — see this package's docstring for why
that boundary is worth keeping.
"""

from __future__ import annotations

import inspect
import logging
import os

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.types import ASGIApp

from . import prompts, resources, tools
from .limits import RateLimitMiddleware

logger = logging.getLogger(__name__)

# Read by the client and shown to the model once per session, so it carries the
# things that would otherwise be rediscovered through failed calls.
INSTRUCTIONS = """\
Annual-mean in-situ aerosol measurements from the EBAS/ACTRIS network, served from a \
local database (no upstream fetches happen during a tool call).

Data is annual only: one mean per station, variable and calendar year. Requests for \
monthly or daily figures cannot be satisfied — say so rather than approximating.

Call get_coverage first. Coverage is uneven across periods and variables, and a period \
outside the matrix has no data rather than data worth retrying for.

Every result carries a provenance block. Values are Level-2 QC'd, but the annual mean is \
unweighted across a station's files and no result states what fraction of a period was \
actually observed. Repeat those caveats when reporting numbers, and carry the citation \
into any published use.
"""

mcp = MCPServer(
    "actris-monitor",
    title="ACTRIS Monitor",
    instructions=INSTRUCTIONS,
    website_url="https://github.com/jisosavi/actris-monitor",
)

# read_only_hint: nothing on this surface writes. open_world_hint=False: it answers
# from a closed set — this database — not the open web.
_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

def _doc(fn) -> str:
    """A docstring the client can render.

    The SDK passes `__doc__` through verbatim, so every line after the first
    arrives with the source's indentation — and four leading spaces is a code block
    to anything that renders the text as markdown. `cleandoc` is the whole fix,
    applied here so nothing has to be written with an ugly docstring.
    """
    return inspect.cleandoc(fn.__doc__ or "")


def _register_tool(fn, *, title: str) -> None:
    mcp.tool(title=title, description=_doc(fn), annotations=_READ_ONLY)(fn)


def _register_resource(fn, *, uri: str, title: str, mime_type: str) -> None:
    mcp.resource(uri, title=title, description=_doc(fn), mime_type=mime_type)(fn)


_register_tool(tools.get_coverage, title="Data coverage")

# Resources are addressed by URI, never by function name, and the SDK does not call
# the function during resources/list — only when a client actually reads one.
_register_resource(
    resources.station_catalog,
    uri="actris://catalog/stations",
    title="Station catalogue",
    mime_type="application/json",
)
_register_resource(
    resources.citation,
    uri="actris://citation",
    title="How to cite this data",
    mime_type="text/markdown",
)

# Prompts are chosen by a person from a menu, so the title is a UI label.
mcp.prompt(
    title="Data availability briefing",
    description=_doc(prompts.data_availability_briefing),
)(prompts.data_availability_briefing)


def _transport_security() -> TransportSecuritySettings | None:
    """Build the Host/Origin allowlist from the environment.

    Returning `None` is deliberate and safe: with no explicit settings and the
    default host, the SDK arms DNS-rebinding protection with a localhost-only
    allowlist, which is exactly right for local development. Behind a real hostname
    that same default answers **every** request with `421 Misdirected Request`,
    logged server-side and reported nowhere else — so `MCP_ALLOWED_HOSTS` is
    required in any deployed environment.
    """
    hosts: list[str] = []
    for raw in os.environ.get("MCP_ALLOWED_HOSTS", "").split(","):
        host = raw.strip()
        if not host:
            continue
        hosts.append(host)
        # The Host header carries the port when it is non-default, and the SDK
        # matches allowlist entries exactly. Both spellings are needed; adding the
        # wildcard here means one env var instead of a footgun.
        if ":" not in host:
            hosts.append(f"{host}:*")

    if not hosts:
        logger.info("MCP_ALLOWED_HOSTS unset: /mcp accepts localhost requests only")
        return None

    # Mirror the dashboard's CORS allowlist for browser clients: the browser
    # enforces CORS, but the transport checks Origin itself and would answer 403
    # even after a clean preflight. "*" is not a value this check understands, so an
    # unrestricted CORS setting means no Origin-bearing client is allowlisted.
    allowed_origin = os.environ.get("ALLOWED_ORIGIN", "*")
    origins = (
        [o.strip() for o in allowed_origin.split(",") if o.strip()]
        if allowed_origin != "*"
        else []
    )

    logger.info("MCP allowed hosts: %s; allowed origins: %s", hosts, origins or "(none)")
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


def build_asgi_app() -> ASGIApp:
    """The app to mount, rate-limited.

    Must be called before `mcp.session_manager` is touched — the manager is created
    here. Calling this once at import time and entering the manager in the host
    app's lifespan is the supported order.
    """
    requests_per_minute = int(os.environ.get("MCP_RATE_LIMIT_PER_MINUTE", "60"))
    max_concurrent = int(os.environ.get("MCP_MAX_CONCURRENT", "8"))

    app = mcp.streamable_http_app(
        transport_security=_transport_security(),
        # Legacy-leg knob only: on protocol 2026-07-28 a request is one
        # self-contained POST with no session. Set because this server needs no
        # server-to-client back-channel (no sampling, no elicitation), so an older
        # client gains restart-tolerance and costs nothing.
        stateless_http=True,
    )

    logger.info(
        "MCP endpoint mounted at /mcp: open (no auth), %d req/min per address, "
        "%d concurrent",
        requests_per_minute,
        max_concurrent,
    )
    return RateLimitMiddleware(
        app,
        requests_per_minute=requests_per_minute,
        max_concurrent=max_concurrent,
    )
