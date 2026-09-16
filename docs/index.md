---
layout: home

hero:
  name: ACTRIS Monitor
  text: Aerosol measurements, for agents
  tagline: >-
    Annual-mean in-situ aerosol data from the EBAS/ACTRIS European research
    network, served over the Model Context Protocol — so an agent can query the
    network directly instead of scraping a dashboard.
  actions:
    - theme: brand
      text: MCP reference
      link: /mcp-reference
    - theme: alt
      text: Open the dashboard ↗
      link: https://www.isosavi.com/test/actris-monitor/
    - theme: alt
      text: GitHub ↗
      link: https://github.com/jisosavi/actris-monitor

features:
  - title: Six tools, two resources, one prompt
    details: >-
      Coverage, station lookup, annual series, rankings, network statistics and
      change between periods. Read-only, and answered from this project's own
      database rather than from NILU.
    link: /mcp-reference
    linkText: Read the reference
  - title: Generated from the running server
    details: >-
      Every description on the reference page is the text the model actually
      receives. The document and the agent's instructions come from the same
      source, so they cannot drift apart.
  - title: Caveats stated, not buried
    details: >-
      Annual only — no monthly or daily figures exist. Means are unweighted
      across a station's files within a year, and no figure says what fraction of
      a period was observed. Both are in every response.
    link: /mcp-server-plan
    linkText: Why the means work that way
---

## Connecting

The endpoint speaks Streamable HTTP and needs no credentials:

```
https://actris-monitor-production.up.railway.app/mcp
```

Add it as an HTTP MCP server in your client. In Claude Code, the repository's
`.mcp.json` already points at it, so opening the project offers the connector.

It is **rate-limited rather than authenticated** — the tools are read-only over
public EBAS data, so there is no credential to hand out, but there is a shared
container behind the URL. Requests are capped per address, with a concurrency
limit; over either, you get `429` or `503` with `Retry-After`. Batch related
questions instead of polling.

## Please cite the data

Every response carries a `provenance` block naming EBAS/ACTRIS. The measurements
are contributed by station principal investigators — acknowledge them, and EBAS
and ACTRIS, in any published use.
