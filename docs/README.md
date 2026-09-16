# docs/

Two things share this directory, and telling them apart matters:

- **The documentation site** — a VitePress project with its own `package.json`,
  published to <https://www.isosavi.com/test/actris-monitor/docs/>.
- **Working notes** — dated decision records for whoever edits the code. Three of
  the four are not published.

Nothing in the filenames says which is which, so:

| File | What it is | Edit it? |
|---|---|---|
| `index.md` | Site landing page | Yes |
| `mcp-getting-started.md` | Site page: connecting an MCP client | Yes |
| `api.md` | Site page: the Scalar REST reference | Yes |
| `mcp-reference.md` | **Generated** from the MCP server | **Never** — see below |
| `mcp-server-plan.md` | Working note, **published** under *Design notes* | Yes |
| `docs-site-plan.md` | Working note: this site's decisions and build order | Yes |
| `nrt-integration-plan.md` | Working note: EBAS near-real-time data | Yes |
| `actris-metadata-api-plan.md` | Working note: ACTRIS metadata API v3 | Yes |
| `public/openapi.json` | **Generated** from the FastAPI routes | **Never** — see below |
| `public/examples/*.json` | A real captured MCP exchange, embedded in the site | Re-capture, don't edit |
| `public/.htaccess` | Server config that ships with the build | Yes |
| `.vitepress/` | Site config and theme | Yes |

The screenshots the root `README.md` uses are deliberately **not** here — they live
in `.github/assets/`, because they illustrate the README rather than the site.

## The two generated files

`mcp-reference.md` comes from `backend/mcp_server/`, and `public/openapi.json` from
the FastAPI routes tagged `Public`. Both carry a do-not-edit marker, and both have a
`--check` flag that CI runs, so an edit here is reverted the next time anyone
regenerates and the check fails in between.

```bash
cd backend
python scripts/dump_mcp_tools.py     # → docs/mcp-reference.md
python scripts/dump_openapi.py       # → docs/public/openapi.json
```

A tool's docstring *is* the description the model reads. That is why the reference
is generated rather than written: a second hand-maintained copy could disagree with
the agent's own instructions and nothing would notice.

## Building the site

`docs/` is an npm package. Install before the first build:

```bash
cd docs && npm ci
npm run build      # → ../frontend/dist/docs
npm run dev        # local preview
```

**Build the frontend first.** The output goes into `frontend/dist/docs` so one
upload carries the dashboard and its documentation together — but `vite build`
empties `frontend/dist`, which takes the docs with it if the order is reversed.

```bash
cd frontend && npx vite build     # first
cd ../docs   && npm run build     # then
```

CI does both in that order and uploads the result as a run artifact, which is the
better thing to deploy — it is built from a known commit rather than from whatever
`frontend/dist` happens to hold.

## Adding a page

Create the markdown file, then add it to `nav` and `sidebar` in
`.vitepress/config.ts` — use the same name in all three places, including the page's
own title. A file that is *not* meant to be published goes in `srcExclude`, or it
appears on the site the next time it builds. This file is in `srcExclude` for that
reason.

The gotchas that cost real time — `vp-raw` on the Scalar page, `cleanUrls` staying
off, VitePress not validating anchors — are in `CLAUDE.md` under *The documentation
site*.
