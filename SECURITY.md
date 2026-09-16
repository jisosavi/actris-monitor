# Security policy

## Reporting a vulnerability

Use GitHub's private reporting:
**[Report a vulnerability](https://github.com/jisosavi/actris-monitor/security/advisories/new)**
— or the *Report a vulnerability* button under the repository's **Security** tab.
The report is visible only to the maintainers until it's resolved.

Please don't open a public issue for anything that could be exploited before it's
fixed.

Include what you did, what happened, and the URL or endpoint involved. I maintain
this alone, so expect a reply in days rather than hours.

## What's in scope

- The deployed backend at `actris-monitor-production.up.railway.app`, including the
  `/mcp` endpoint and the `/api/*` routes.
- The dashboard at `www.isosavi.com/test/actris-monitor/`.
- Anything in this repository.

## What is deliberately open

Worth stating so it isn't reported as a finding:

**The MCP endpoint is unauthenticated on purpose.** It serves public EBAS data from
this project's own database, so a token would protect the container rather than the
data. The protections are a per-address rate limit and a concurrency cap, both
in-process counters. If you can get past those, or make a tool call reach NILU's
servers, that *is* a finding — the MCP path must never make an upstream request.

**The REST read endpoints are unauthenticated**, for the same reason.

**The three mutating endpoints** — `/api/start-fetch`, `/api/db/reset` and
`/api/backfill-networks` — require an `X-Admin-Token` header and fail closed: with
`ADMIN_TOKEN` unset they return 503 rather than being open. A way around that is a
finding, and a serious one.

## Out of scope

- The upstream data sources: `thredds.nilu.no`, `prod-actris-md.nilu.no` and
  `ebas-nrt.nilu.no` belong to NILU. Please don't test against them. Report issues
  there to NILU directly.
- Measurement values being wrong or surprising. That's a data question, not a
  security one — the known caveats are in
  [the design notes](https://www.isosavi.com/test/actris-monitor/docs/mcp-server-plan.html).
- Missing rate limits on a self-hosted copy you're running yourself.
