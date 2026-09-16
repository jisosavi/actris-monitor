---
layout: page
title: REST API
---

<div class="api-intro">

# REST API

The read-only HTTP surface behind the dashboard. Six endpoints, no authentication,
served from this project's own database — no request here reaches NILU.

Base URL:

```
https://actris-monitor-production.up.railway.app
```

| Endpoint | Returns |
|---|---|
| `GET /api/stations/{year}/{variable}` | One annual mean per station, highest first |
| `GET /api/network-stats/{year}/{variable}` | Median, quartiles and range across stations |
| `GET /api/db-status` | Which year and variable combinations hold data |
| `GET /api/variables` | Key, label and unit for the three variables |
| `GET /api/actris/facilities` | ACTRIS facility metadata by EBAS station code |
| `GET /api/nrt/stations` | Stations with EBAS near-real-time data |

The machine-readable document is **[openapi.json](./openapi.json)** (OpenAPI 3.1).
It is generated from the running application and contains only these six routes;
administrative and internal endpoints exist and are deliberately absent.

`{variable}` is one of `N`, `scattering` or `absorption`. `{year}` is a calendar
year from 2000 — **data is annual**, and monthly or daily figures cannot be derived
from these endpoints. Annual means are unweighted across a station's files and may
mix size cuts, and no field says what fraction of a year was observed. See
[the design notes](./mcp-server-plan).

Building an agent? The [MCP endpoint](./mcp-getting-started) is the better door —
it carries provenance on every response.

<noscript>

**The interactive explorer below needs JavaScript.** Everything it shows comes from
[openapi.json](./openapi.json), which you can read directly.

</noscript>

</div>

<ScalarReference />

<style>
.api-intro {
  max-width: 768px;
  margin: 0 auto;
  padding: 32px 24px 8px;
}
.api-intro h1 { font-size: 2rem; font-weight: 700; margin-bottom: 16px; }
.api-intro p { margin: 16px 0; line-height: 1.7; }
.api-intro table { display: table; width: 100%; margin: 20px 0; font-size: 14px; }
.api-intro code { font-size: 0.9em; }
</style>
