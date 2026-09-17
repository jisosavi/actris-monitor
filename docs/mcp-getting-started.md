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

**Any other client** — add it as an HTTP (Streamable HTTP) server. Most take some
form of this, which is also what `.mcp.json` in the repository contains:

```json
{
  "mcpServers": {
    "actris-monitor": {
      "type": "http",
      "url": "https://actris-monitor-production.up.railway.app/mcp"
    }
  }
}
```

There is no token, no header and no session to configure.

## Checking it by hand

A liveness check needs nothing but a POST. This lists the tools:

```bash
curl -sX POST https://actris-monitor-production.up.railway.app/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

The response is an SSE frame — `event: message` followed by a `data:` line holding
the JSON-RPC result.

::: warning The protocol era is chosen by a header, not by the body
That request is served on the **legacy** path, because it carries no
`MCP-Protocol-Version` header. On that path the 2026-07-28 methods do not exist:
`server/discover` returns `-32601 Method not found`, and capabilities report
`listChanged: false`. Nothing is broken — the request simply asked for an older
protocol without saying so.

Putting the version in `params._meta` does **not** help. The transport routes on the
header alone and never inspects the body.
:::

A 2026-07-28 request needs three things together — the header, an `Mcp-Method` that
matches the body, and the `_meta` envelope:

```bash
curl -sX POST https://actris-monitor-production.up.railway.app/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: server/discover' \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover",
       "params":{"_meta":{
         "io.modelcontextprotocol/protocolVersion":"2026-07-28",
         "io.modelcontextprotocol/clientCapabilities":{}}}}'
```

That returns the server's capabilities and the instructions the model receives. Omit
any one of the three and you get a specific complaint: `-32601` for the missing
header, `-32020` for a mismatched `Mcp-Method`, `-32602` for a missing `_meta`
envelope.

A real client handles all of this. This is for proving the endpoint is up, and for
working out which era your client actually negotiated.

::: tip A new tool is invisible until you reconnect
The protocol does have a push channel — `subscriptions/listen`, which a client opts
into per notification type. But this server never uses it: its tool list cannot
change while the process runs, and it changes by redeploying, which drops any open
stream. A client may also be reusing a cached `tools/list` until its `ttlMs`
expires. So if something documented here is missing from your client, toggle the
connector off and on.
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

## A call, and what comes back

Captured from the live endpoint on 2026-09-16, unedited. Both files are fetchable:
[request](./examples/get-series-request.json),
[response](./examples/get-series-response.json).

<<< @/public/examples/get-series-request.json [tools/call request]

<<< @/public/examples/get-series-response.json{json} [response]

Three things in there are worth pointing at, because they are the conventions most
often misread:

**`"mean": null` for Hyytiälä in 2024 is data, not an omission.** Every period in
the requested range comes back as a row. A period missing from `rows` would be
indistinguishable from one that was never asked for, so gaps are explicit.

**`provenance` is on the response, not in the documentation.** It travels with the
numbers because that is the only form that survives being pasted into something
else. `mean_method` is the one to read before comparing two stations.

**`truncated` and `n_remaining` are zero here**, but `get_series` caps at 10
stations and drops *whole* stations when it truncates — never part of a station's
record, which would read as a complete series and invite a trend that is not there.

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
- **How much of the year was actually observed varies enormously**, and
  `observed_fraction` now says so: the share of the period's hours holding a usable
  value, 0–1. A station at 0.95 and one at 0.30 both report a single annual mean,
  and the second one's is worth much less. `null` means it could not be determined,
  which is not the same as `0.0`.

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
