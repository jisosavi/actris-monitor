# Documentation site plan

A published documentation site for this project, aimed at the people connecting an
agent to `/mcp`. Investigated 2026-09-16.

**Status: done.** All phases, including the optional CI workflow, are built and
live at <https://www.isosavi.com/test/actris-monitor/docs/>. Two rounds of external
review have been through it since. The gotchas worth carrying forward are in
`CLAUDE.md` under *The documentation site*; this document is now a record of how it
was decided rather than a list of work.
This document remains the decision record and the build order.

The short version: **VitePress** for the site, **Scalar** for the API reference
page inside it, hosted as static files next to the dashboard on isosavi.com. No
subscription, no third-party account, the repository stays the source of truth.

## Decisions already made

| Question | Decision | Why |
|---|---|---|
| Audience | **Agent / MCP client developers and operators** | The MCP endpoint is the public programmatic interface. The REST API is an implementation detail of the dashboard |
| Framework | **VitePress**, stable 1.6.x | Static output we can host ourselves, Vite/Vue toolchain already in the repo, markdown files stay where they are |
| Docs platform | **Not Scalar Docs** | Hosted-only, and our own domain starts at $150/mo. See below |
| API reference | **Scalar `@scalar/api-reference`, self-hosted** | MIT, npm dependency, no account, no CDN |
| REST surface published | **Read endpoints only** | Admin and debug routes excluded from the published document, not merely undocumented |
| Source of truth | **The repository, always** | `mcp-reference.md` is generated and gated; a second editable copy anywhere would defeat that |
| Plan docs | **Not published** — `srcExclude`, link to GitHub | They are working notes, not integrator documentation. The site stays tight around one audience |
| Discovery from the app | **The existing "About this app" button** | A human visitor's only route to the docs. See the constraint on that sidebar below |
| Visual design | **Default theme, dashboard colours** | Familiar to the audience, and the two properties read as one project. No custom theme |

## Why not Scalar Docs

Worth writing down, because the marketing copy invites the opposite conclusion and
someone will propose it again.

Scalar sells three separable things. The **API Reference renderer** and **API
Client** are MIT and genuinely self-hostable — `github.com/scalar/scalar` ships
`api-reference`, `api-client`, `openapi-parser`, `themes`, `sidebar`,
`server-side-rendering` and friends. The **Docs platform** (markdown/MDX guides,
navigation, search, `scalar.config.json`) is **not in that repository** and has no
build or export command: the CLI is `project preview`, `project publish`,
`publish --preview`, `publish --github`, `deployments list`, `rollback`. Publish
uploads to Scalar's servers. The **Agent product** generates an MCP server *from*
an OpenAPI document, which is the opposite direction from ours and would put a
proxy outside our in-process rate limiter.

Scalar's own pages say "self-host it, it's open source". That sentence is about
the renderer and the client. It gets restated loosely enough to sound like it
covers the guides platform. It does not.

Pricing, if this is ever revisited: Free is a `*.scalar.app` subdomain, 1 editor
seat, 3 APIs, 25 endpoints. A custom domain (`docs.isosavi.com`) starts at Pro,
$150/month. Hosting under a *subpath* — which is where this project's docs would
naturally sit — is listed as a Business feature, $600/month.

So Scalar Docs would cost $150–600/month to render markdown we already have, for
an audience whose primary document (`mcp-reference.md`) it has no special
understanding of. The renderer, meanwhile, is free and fits.

## What VitePress is

A static site generator built on Vite and Vue 3, by the Vue team; it is what
Vite's, Vue's, Pinia's and Vitest's own documentation runs on. It takes a
directory of markdown files plus a config, and emits plain HTML/CSS/JS you can
copy onto any web server.

What makes it the right fit here specifically:

- **It consumes the markdown we already have**, in place. No migration, no MDX, no
  front-matter requirements. `docs/*.md` stays exactly as `dump_mcp_tools.py`
  writes it.
- **Static output, no runtime.** Builds to a directory; deploys the same way the
  dashboard already deploys. Nothing new to run, nothing to pay for.
- **`base` handles subpath deployment** — the same problem `VITE_BASE_PATH`
  already solves for the frontend.
- **Local search is built in** (`themeConfig.search = { provider: 'local' }`), a
  client-side MiniSearch index. No Algolia account, no external request.
- **Vue components work inside markdown**, which is how the Scalar API reference
  becomes a page rather than a separate site.
- The first visit is pre-rendered HTML — it works without JavaScript and indexes
  properly — then it hydrates into an SPA for subsequent navigation.

### Version note, and why the docs site is its own npm project

VitePress stable is **1.6.4**, which depends on Vite `^5.4` and Vue `^3.5`. The
dashboard in `frontend/` is on **Vite 8** and TypeScript 6. VitePress 2 (Vite 8)
exists only as `2.0.0-alpha.20`.

Do not try to reconcile these. The docs site gets **its own `package.json` and its
own `node_modules`** under `docs/`, with no workspace link to `frontend/`. Two
independent Vite versions in two independent projects is a non-event; one
lockfile trying to satisfy both is a weekend.

Track VitePress 2 and move when it is stable. Nothing in the plan depends on it.

## Design

### Layout

VitePress's default convention puts the config inside the content directory, which
means `docs/` becomes the site with no files moved:

As built — an earlier draft of this diagram proposed an `mcp/` subdirectory and
`openapi.json` at the docs root; neither survived contact with the build:

```
docs/
  .vitepress/
    config.ts            base, nav, sidebar, search, srcExclude, buildEnd
    theme/index.ts       registers the client-only Scalar component
    theme/custom.css     the dashboard palette, copied not imported
    theme/ScalarReference.vue
  package.json           vitepress + @scalar/api-reference, separate from frontend/
  README.md              what this directory is (srcExclude'd)
  index.md               site landing page (NOT a copy of README.md)
  mcp-getting-started.md connecting a client
  mcp-reference.md       generated by dump_mcp_tools.py
  api.md                 the Scalar reference page
  public/openapi.json    generated by dump_openapi.py, Public routes only
  public/examples/       a real captured MCP exchange, embedded and tested
  public/.htaccess       neutralises the dashboard's catch-all
  *-plan.md              present; only mcp-server-plan.md is published
```

Flat filenames rather than a subdirectory, because `rewrites` would have been a
second place for a path to be wrong. The constraint that mattered held:
**`dump_mcp_tools.py` keeps owning `mcp-reference.md`**. If the path changes, the
script's `OUTPUT` changes and `CLAUDE.md` follows. It never becomes two files.

### README.md stays put, and stays different

`README.md` is GitHub's landing page and must keep working as one. The site's
`index.md` is not a copy of it — it is a short hero page that routes the two
audiences apart: "connect an agent" to the MCP section, "see the data" to the live
dashboard. Duplicated prose is how the two drift.

### The Scalar page

`@scalar/api-reference` is **1.68.0, MIT, 25 dependencies, no peer dependencies**,
and exports `./components` and `./style.css`. It is a Vue 3 component, installed
as a normal dependency — nothing is fetched from a CDN at runtime, which is the
whole point of using the package rather than `scalar-fastapi`.

Two mechanics to get right:

- **It must be client-only.** VitePress pre-renders every page; the Scalar
  component is not SSR-safe. Register it with `defineClientComponent` in the
  custom theme, or wrap the usage in `<ClientOnly>`. Skipping this fails at build
  time, loudly, which is the good kind of failure.
- **Keep it on its own route.** Scalar is a large bundle. VitePress code-splits per
  page, so a client-only import on `api.md` alone leaves every other page — the
  ones the MCP audience actually reads — unaffected.

The reference gets the spec from `openapi.json` served alongside it.

### One plan doc is published; three are not

`mcp-server-plan.md` **is published**, in a *Design notes* section. It holds the
clearest existing account of what the annual means are *not* — the unweighted
averaging, the mixed size cuts, the year-to-year step that comes from a file
appearing rather than from the atmosphere. For someone deciding whether to trust a
number their agent just returned, that is the most useful page on the site.

`nrt-integration-plan.md`, `actris-metadata-api-plan.md` and this document stay in
`docs/` and are **excluded** via `srcExclude`. Two of them are internal data
plumbing of no concern to someone connecting a client, and the NRT one opens with
a bug post-mortem — candour among people editing the code, instability to a
stranger evaluating the data. They remain public in the repository and the site
links to GitHub for anyone who wants them.

**The published one needs a standing preamble**, added at build time rather than
edited into the file: *working notes, dated, describing what was decided and why —
not a commitment to build what is listed as unbuilt.* Without it a reader plans
around monthly resolution arriving. This is the one piece of publishing a working
note that is not free.

Verified by building, not assumed: `mcp-server-plan.md` compiles unmodified.

An earlier draft called the `<id>` in `actris-metadata-api-plan.md` a
Vue-parsing hazard. It is not — it sits inside a code span
(`` `https://data.actris.eu/facility/<id>` ``), which markdown-it renders as
`<code>` before Vue ever sees it. The scan that flagged it matched angle
brackets without checking for surrounding backticks. **There are no
Vue-parsing hazards anywhere in this repository's markdown**, published or
excluded, and nothing needs fixing before publishing any of it.

Because the design note is on the site, the MCP getting-started page can state the
two caveats briefly and link to it, rather than re-explaining them in full.

### Theme

The default VitePress theme, retinted to the dashboard's palette. That is a
`.vitepress/theme/custom.css` overriding VitePress's CSS variables — no custom
components, no layout work.

The source of truth for the colours is `frontend/src/assets/main.css`, whose
`:root` block carries the app tokens (`--accent: #303193`, `--bg: #eef1f7`,
`--text: #1a1d3d`, `--border: #d8dff0`) under a comment describing them as
shadcn tokens mapped to the FMI palette. There is a matching `.dark` block, so
both of VitePress's themes can be mapped rather than only the light one.

**Copy the values; do not import the file.** It pulls in Tailwind, MapLibre's
stylesheet and `tw-animate-css`, none of which belong in a documentation build.
A dozen hex values duplicated into `custom.css` is the smaller problem — and if
the palette ever changes, the site being slightly off-brand is a cosmetic bug,
whereas a docs build coupled to the dashboard's CSS pipeline is a real one.

### Linking from the dashboard

The "About this app ↗" button in `frontend/src/components/AdminPanel.vue` is
today an `<a>` straight to `REPOSITORY_URL`. It becomes a button that **opens a
dialog offering two destinations**: the documentation site and the GitHub
repository.

A dialog rather than a second button, and this is not stylistic. The scoped style
in that component carries a comment recording that two stacked buttons already
overflow the sidebar on a 1000px window — enough to push *Data Setup* out of
sight, a real bug someone fixed. The sidebar has no room for a third control, and
a dialog adds none.

`components/ui/` currently holds `badge`, `button`, `card`, `select` and
`separator` — **no dialog**. `reka-ui` is already a dependency, so the shadcn-vue
dialog generates cleanly on top of it:

```bash
cd frontend && npx shadcn-vue@latest add dialog
```

That writes into `components/ui/dialog/`, which `CLAUDE.md` marks as generated —
so it is added by the generator and left alone afterwards, like the other five.

The dialog is two labelled links, each saying where it goes and why: the docs for
using the data and the MCP endpoint, GitHub for the code and the issue tracker.
No version string — it would be one more thing to forget to update.

The docs href depends on the deploy path settled in phase 0, so this lands last.
It is the only frontend change in the plan, and it needs
`npm run type-check && npm run lint` before committing.

### The curated OpenAPI document

`backend/main.py` has **15 routes and zero `summary=`, `description=` or `tags=`**.
The published document should contain only the read endpoints:
`/api/stations/{year}/{variable}`, `/api/network-stats/{year}/{variable}`,
`/api/variables`, `/api/db-status`, `/api/nrt/stations`, `/api/actris/facilities`.

**Tag the routes, filter in a script — don't use `include_in_schema=False`.**
Setting that flag removes the admin endpoints from FastAPI's own `/docs` too, and
the operator running a fetch is exactly the person who benefits from having them
there. Instead: tag every route `Public`, `Admin` or `Internal`, and add
`backend/scripts/dump_openapi.py` that emits only the `Public` ones to
`docs/openapi.json`.

That script is deliberately a sibling of `dump_mcp_tools.py`: same shape, same
`--check` flag, same "generated, do not hand-edit" banner. One more generated
artefact under the same rule is cheap; a second, different convention is not.

Writing the descriptions is the real work in this phase. The generator is an hour;
annotating six endpoints so the page is worth publishing is most of a day.

### Try-it, and CORS

Scalar's reference includes a request runner. Firing it from
`isosavi.com` against the Railway backend is a cross-origin request, so
`ALLOWED_ORIGIN` must include the docs origin — the same variable `CLAUDE.md`
already flags, now with one more reason to be set correctly in production.

If that turns out to be more trouble than it is worth, the runner can be disabled
and the page left as a reference. The reference is the part that matters.

## Deployment

The dashboard is built with `npm run build` and the static output is placed at
`isosavi.com/test/actris-monitor/`. The docs build the same way
(`vitepress build`, output in `docs/.vitepress/dist`) and are copied to
`/test/actris-monitor/docs/`, with `base: '/test/actris-monitor/docs/'` in the
config.

### What the live host actually does

Probed 2026-09-16 against `www.isosavi.com`, Apache:

- **A non-existent path returns the dashboard.** `/test/actris-monitor/zzz` comes
  back `200 text/html`, byte-identical to `/test/actris-monitor/index.html`. There
  is a catch-all rewrite, even though the dashboard has **no `vue-router`** and
  therefore never needed one.
- **Real files are served, not rewritten.** `/test/actris-monitor/assets/index-*.js`
  returns 2.4 MB of `text/javascript`. So the rewrite carries a `!-f` condition
  and a real subdirectory of real files is safe.

This is good news with one sharp edge.

**Set `cleanUrls: false`** — which is VitePress's default, so this is really "do
not turn it on". With clean URLs, `/docs/mcp/getting-started` has no file behind
it (the file is `getting-started.html`), the `!-f` condition fails, and the
catch-all serves **the dashboard** in place of the docs page. Not a 404 — the map.
With clean URLs off, every route is a real `.html` file, the fallback never fires,
and a hard refresh or a shared deep link resolves correctly.

Clean URLs are recoverable later by dropping an `.htaccess` inside the docs
directory with its own rewrite rules, if `AllowOverride` permits it. Not worth it
for the first release; `.html` in a docs URL has never confused anyone.

**One thing still needs a live test**, because it cannot be answered by probing a
path that does not exist yet: whether `/test/actris-monitor/docs/` resolves to
`docs/index.html` via `DirectoryIndex`, or whether the rewrite intercepts the bare
directory first (it depends on a `!-d` condition we cannot see). Upload a folder
containing one `index.html` and request it with and without the trailing slash.
If the directory form loses, link to `docs/index.html` explicitly, or use the
sibling path `/test/actris-monitor-docs/`.

**A confusing failure mode to know about:** because of the catch-all, a mistyped
docs URL renders the dashboard rather than a 404. Dead internal links will not
announce themselves in production. Keep `ignoreDeadLinks` off so the *build*
catches them instead.

There is **no `.github/` directory in this repository** and therefore no CI. The
`--check` flags on the generator scripts are run by hand today. The plan does not
assume that changes, but it is the obvious moment to add a workflow that runs
`dump_mcp_tools.py --check`, `dump_openapi.py --check` and the VitePress build on
push. Until then, the release ritual is: regenerate, build, upload.

## Risks

**Vue parsing of existing markdown.** VitePress compiles markdown to Vue
components, so `{{ }}` becomes interpolation and `<tag>` becomes a component
lookup. The existing files were checked: **zero occurrences of `{{`** anywhere,
and the only raw tags are 100 `<br>` in `mcp-reference.md` (a native element,
fine), one `<https://ebas-nrt.nilu.no>` autolink (fine), and **one `<id>` in
`actris-metadata-api-plan.md`, which will break the build** and needs backticks.
That is the entire migration cost of the prose — and with the plan docs excluded
from the build, the `<id>` is not even that. It stays a fix worth making rather
than a blocker.

If `dump_mcp_tools.py` ever emits a `{` pair or a novel tag, the docs build starts
failing on generated content. Cheap insurance: run the docs build in the same
breath as `--check`.

**The generated reference gains a second consumer.** Today the file has one reader
and a staleness gate. After this it also has a published URL, so "regenerated but
not deployed" becomes a new way to be silently wrong. The mitigation is the CI
workflow above, and until it exists, discipline.

**Scope creep into a documentation project.** The audience is MCP operators. The
first release is: landing page, connect-a-client guide, the generated reference,
the API page. Not a tutorial series.

## Deliberately not chosen

- **Scalar Docs** — hosted-only and $150/month minimum for our own domain, for
  markdown rendering. See above.
- **`scalar-fastapi` on the backend** — three lines and tempting, but it defaults
  to loading the renderer from jsdelivr, and it puts another public route on the
  Railway container we are deliberately keeping small and rate-limited. The npm
  dependency in the docs site is self-contained.
- **A docs route inside the existing Vue app** — means hand-rolling markdown
  rendering, a sidebar and search inside an app whose job is a map. VitePress is
  that work, already done.
- **Publishing `CLAUDE.md`** — it is written for whoever is editing the code, and
  its value is being next to the code. It stays repository-only.
- **Moving the plan docs out of `docs/`** — they stay, and the site can publish
  them under a clearly-labelled section. Whether it should is an open question.

## Verification

1. A folder containing one `index.html` at `/test/actris-monitor/docs/` is served
   both as `/docs/` and as `/docs/index.html`. **Do this first** — it is the only
   part of the host's behaviour still unknown.
2. A deep page — `/docs/mcp/reference.html` — survives a hard refresh rather than
   rendering the dashboard.
3. `vitepress build` succeeds over the existing `docs/*.md` unchanged, apart from
   the `<id>` fix.
4. The Scalar page renders the curated `openapi.json` and shows exactly six
   endpoints — no `/api/db/reset`, no `/api/debug/station/{id}`.
5. `dump_openapi.py --check` fails after a route is retagged, and passes after a
   regenerate.
6. Local search returns a tool name — `get_change` — from the generated reference.
7. The site works on a phone, and with JavaScript disabled for the first paint.

## Effort

| Phase | What | Estimate |
|---|---|---|
| 0 | Directory-index test on the host, the `<id>` fix | 30 min |
| 1 | VitePress skeleton: config, nav, sidebar, search, existing docs building | half a day |
| 2 | Tag the routes, `dump_openapi.py`, write the six endpoint descriptions | most of a day |
| 3 | Scalar page: dependency, client-only registration, spec wiring, CORS check | 2–3 hours |
| 3b | Retint the default theme from `main.css`, light and dark | half a day |
| 4 | New prose: landing page, MCP getting-started incl. the data caveats | half a day |
| 4b | Repoint "About this app" at the site, plus type-check and lint | 30 min |
| 5 | Optional CI workflow: both `--check`s plus the docs build | 1–2 hours |

Roughly two days, and phase 2 was most of it — writing the descriptions is the part
no tool does for you.

Phase 5 grew in the building. As well as the checks, CI uploads the built site as a
run artifact, which is the better thing to deploy: it comes from a known commit
rather than from whatever `frontend/dist` happens to hold, which is the failure that
once shipped a two-week-old bundle. It also asserts that the machine-readable
formats are still advertised — a character count on the REST page would have failed
the better version of that page.

What is *not* in the estimate is the work that came after: two external reviews, the
generated reference under-reporting its own schemas, and a worked example with tests
to keep it honest. A plan predicts the building, not the reading.

## Two findings worth keeping

Both are resolved. They are recorded because each looked like something else first.

**The bare directory form did not work, and now does.** Answered by uploading,
which is the only way it could have been.

Probing a sibling app at `/test/ikimetsat/` established that `DirectoryIndex`
works on this server and that misses 404 normally there — so the dashboard's
catch-all is **scoped to `/test/actris-monitor/`**, not server-wide. But an
`.htaccess` applies to subdirectories, so the docs nested inside it inherited the
rewrite. A *directory* is not a file, so the rewrite's `!-f` test passed and
`/test/actris-monitor/docs/` was answered with the dashboard.

It was not obvious from a browser. Both pages are titled "ACTRIS Monitor", so the
bare directory form looked like it worked. The byte count gave it away: 767 bytes,
which is exactly the dashboard's SPA shell, against 13,862 for the real landing
page.

The fix ships with the site, as `docs/public/.htaccess` — VitePress copies
`public/` to the output root, dotfiles included:

```apache
RewriteEngine Off
DirectoryIndex index.html
```

That makes the directory behave like any other on the server: `/docs/` resolves
to `index.html`, and a missing page is an honest 404 rather than a silent
redirect to the map. It also means the nested path costs nothing that the sibling
path would have saved, so `/test/actris-monitor/docs/` stands.

`cleanUrls` still stays off. With the rewrite disabled there is nothing left to
map `/mcp-reference` onto `/mcp-reference.html`.

### CORS on the try-it runner: not a problem after all

An earlier draft listed this as an unknown. It is not. An *origin* is scheme, host
and port — the path plays no part. Hosting the docs under
`www.isosavi.com/test/actris-monitor/docs/` puts them on **exactly the origin the
dashboard already runs on**, so the try-it requests to the Railway backend are
indistinguishable from the ones the dashboard makes all day, and `ALLOWED_ORIGIN`
already covers them.

This only returns if the docs ever move to a different host or a `docs.` subdomain
— which is a further argument for the subdirectory.
