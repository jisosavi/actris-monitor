---
layout: page
title: REST API
---

<div class="vp-doc api-intro">

# REST API

Six read-only endpoints behind the dashboard, served from this project's own
database — no request here reaches NILU. Explore them below, or take the spec.

<div class="api-facts">

**Base URL** `https://actris-monitor-production.up.railway.app`

**Machine-readable** [openapi.json](./openapi.json) · [llms.txt](./llms.txt)

</div>

<noscript>

**The explorer below needs JavaScript.** Everything it shows comes from
[openapi.json](./openapi.json) — the base URL, all six endpoints, their parameters
and the data caveats. Read that instead.

</noscript>

</div>

<ScalarReference />

<style>
.api-intro {
  max-width: 768px;
  margin: 0 auto;
  padding: 40px 24px 4px;
}
.api-intro h1 {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 12px;
}
.api-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 32px;
  margin-top: 20px;
  padding: 14px 18px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 8px;
  background: var(--vp-c-bg-soft);
  font-size: 14px;
}
.api-facts p { margin: 0 !important; }
.api-facts strong {
  color: var(--vp-c-text-2);
  font-weight: 500;
  margin-right: 6px;
}
.api-facts code { font-size: 0.9em; }
</style>
