# Documentation site plan

A published documentation site for this project, aimed at the people connecting an
agent to `/mcp`. Investigated 2026-09-16. **Not implemented** — this document is
the decision record and the build order.

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

```
docs/
  .vitepress/
    config.ts            base, nav, sidebar, local search
    theme/index.ts       registers the client-only Scalar component
  package.json           vitepress + @scalar/api-reference, separate from frontend/
  index.md               site landing page (NOT a copy of README.md)
  mcp/
    getting-started.md   new prose: connect a client, what to expect
    reference.md         → the generated docs/mcp-reference.md
  api.md                 the Scalar reference page
  openapi.json           generated, read endpoints only
  *-plan.md              present, but srcExclude'd — not published
```

Whether the generated reference is re-pointed into `mcp/` or left at
`docs/mcp-reference.md` and routed with `rewrites` is a detail for the build; the
constraint is that **`dump_mcp_tools.py` keeps owning the file**. If the path
changes, the script's `OUTPUT` changes and `CLAUDE.md` follows. It never becomes
two files.

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

### What is not published

The four `*-plan.md` files stay in `docs/` and are **excluded from the build** via
`srcExclude`. They are working notes — decision records for whoever edits the code
— and the site is for someone connecting a client. They remain public in the
repository, and the site links to GitHub for anyone who wants the reasoning.

One useful side effect: excluding them removes the **only** Vue-parsing hazard in
the repository, the `<id>` in `actris-metadata-api-plan.md`. The published set —
`mcp-reference.md` plus new prose — contains nothing VitePress can choke on. Fix
the `<id>` anyway, as cheap insurance against a later decision to publish them,
but it is no longer on the critical path.

The trade-off, stated so it can be revisited: `mcp-server-plan.md` contains the
clearest existing explanation of what the annual means are *not*, and that is
genuinely integrator-facing. The MCP getting-started page must therefore carry
those caveats itself rather than linking out to a document that is not on the
site.

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

The "About this app ↗" button in `frontend/src/components/AdminPanel.vue`
currently points at `REPOSITORY_URL`. Once the site exists, **repoint it there**
rather than adding a button: the docs site becomes the better front door, and it
can link onward to GitHub.

This is not stylistic. The scoped style in that component carries a comment
recording that two stacked buttons already overflow the sidebar on a 1000px
window — enough to push *Data Setup* out of sight, which was a real bug someone
fixed. A third button would regress it.

The href depends on the deploy path settled in phase 0, so this change lands last.
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

Roughly two days, and phase 2 is most of it — because writing the descriptions is
the part no tool does for you.

## Still open

Everything about scope is decided. Two facts remain unknown, both answerable only
by doing:

- **Does the bare directory form resolve?** Whether `/test/actris-monitor/docs/`
  reaches `docs/index.html` via `DirectoryIndex`, or the catch-all intercepts it
  first. Phase 0, one folder with one file. If it loses, the sibling path
  `/test/actris-monitor-docs/` sidesteps it entirely.
- **Is the try-it runner worth keeping?** It needs `ALLOWED_ORIGIN` to include the
  docs origin. If that proves awkward, disable the runner — the reference is the
  part that matters.
