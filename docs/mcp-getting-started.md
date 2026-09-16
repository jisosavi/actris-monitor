# Connecting a client

The dashboard's backend also speaks the [Model Context Protocol](https://modelcontextprotocol.io)
at `/mcp`, over Streamable HTTP. An agent can query the network directly instead
of scraping the map.

```
https://actris-monitor-production.up.railway.app/mcp
```

## Adding it

**Claude Code** — the repository ships an `.mcp.json` pointing at the endpoint, so
opening the project offers the connector and asks before enabling it. Without the
repository:

```bash
claude mcp add --transport http actris-monitor \
  https://actris-monitor-production.up.railway.app/mcp
```

**Claude Desktop and other clients** — add it as an HTTP (Streamable HTTP) MCP
server. There is no token to configure.

::: tip A new tool is invisible until you reconnect
The server advertises `listChanged`, but the stateless transport has no channel to
push on — a client discovers the surface once, when its connection is established.
If something documented here is missing from your client, toggle the connector off
and on.
:::

## Start with `get_coverage`

Coverage is uneven across years and variables, and a year outside the matrix has
no data rather than data worth retrying for. `get_coverage` returns the
availability matrix and each variable's definition, which is the cheapest way to
find out what can be asked.

Station codes like `FI0050R` are what every other tool takes. Resolve a name with
`find_station` rather than guessing.

**The current year is normally empty.** Level 2 publication lags by a year or two,
so the latest period in the matrix is not "now".

## What the data is, and is not

Three variables — particle number concentration, light scattering and light
absorption — Level 2 quality-assured, 2000 onwards.

**It is annual.** One mean per station, variable and calendar year. Monthly and
daily figures do not exist in this database and cannot be derived from it. A tool
asked for them will say so rather than approximate.

Two caveats travel with every response, in a `provenance` block, and any answer
built on these numbers should repeat them:

- **The annual mean is unweighted across a station's files.** Where a station
  published more than one Level 2 file for a year, they are averaged flat — and
  those files may use different size cuts. A step between two years can therefore
  come from a file appearing rather than from a change in the atmosphere.
- **No figure states what fraction of a year was observed.** There is a
  `data_coverage` field, but it is a has-data flag despite the name.

Neither is a bug, and the reasoning is worth reading before publishing anything
built on these numbers — see *The aggregation question* in
[the design notes](/mcp-server-plan).

## Limits

Open, and rate-limited rather than authenticated: the tools are read-only over
public EBAS data, so there is no credential to hand out, but there is one shared
container behind the URL.

| | |
|---|---|
| Requests | 60 per minute, per address |
| Concurrency | 8 in flight |
| Over either | `429` or `503`, with `Retry-After` |

Batch related questions rather than polling. No tool call reaches NILU — every
answer is served from this service's own database, or reports the data as absent.

## Please cite the data

The measurements are contributed by station principal investigators. Acknowledge
them, and EBAS and ACTRIS, in any published use. The `actris://citation` resource
holds text to paste into a manuscript.

---

Next: [the full reference](/mcp-reference) — every tool, resource and prompt, with
the exact descriptions the model receives.
