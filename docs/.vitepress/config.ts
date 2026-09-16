import { defineConfig } from 'vitepress'
import type { Plugin } from 'vite'

// The deploy path. Overridable the way the dashboard's VITE_BASE_PATH is, so a
// preview can be built for a different location without editing this file.
const BASE = process.env.DOCS_BASE ?? '/test/actris-monitor/docs/'

// Built straight into the dashboard's output directory, so one upload carries
// both. The frontend build must run FIRST — Vite empties frontend/dist, which
// would take the docs with it.
const OUT_DIR = process.env.DOCS_OUT_DIR ?? '../frontend/dist/docs'

const REPO = 'https://github.com/jisosavi/actris-monitor'
const APP = 'https://www.isosavi.com/test/actris-monitor/'
const MCP = 'https://actris-monitor-production.up.railway.app/mcp'

/**
 * Prepend a standing note to the one working-note document we publish.
 *
 * `mcp-server-plan.md` is a decision record written for whoever edits the code:
 * it is dated, and its unbuilt sections are options rather than promises. A
 * reader arriving from the site does not know that, and would reasonably plan
 * around monthly resolution arriving.
 *
 * Injected at build time rather than edited into the file because the file is
 * also read on GitHub, where the note would be noise — and because a plan doc
 * should not carry instructions for a publishing pipeline it knows nothing about.
 */
function planDocPreamble(): Plugin {
  const NOTE = [
    '::: warning These are working notes',
    'A dated decision record, published because it is the clearest account of what',
    'the annual means are — and are not. Sections describing unbuilt work are',
    'options that were considered, not commitments. Nothing here overrides the',
    '[MCP reference](/mcp-reference), which is generated from the running server.',
    ':::',
  ].join('\n')

  return {
    name: 'actris-plan-doc-preamble',
    enforce: 'pre',
    transform(code, id) {
      if (!id.endsWith('mcp-server-plan.md')) return
      // After the H1, so the page keeps its title as the first thing on it.
      const lines = code.split('\n')
      const h1 = lines.findIndex((l) => l.startsWith('# '))
      if (h1 === -1) return
      lines.splice(h1 + 1, 0, '', NOTE)
      return { code: lines.join('\n'), map: null }
    },
  }
}

export default defineConfig({
  title: 'ACTRIS Monitor',
  description:
    'Annual-mean aerosol measurements from the EBAS/ACTRIS network, for agents and API clients.',
  base: BASE,
  outDir: OUT_DIR,
  lang: 'en-GB',

  // Deliberately OFF. The dashboard's directory on the server carries a catch-all
  // rewrite that serves the app whenever the requested path is not a real file.
  // With clean URLs, /mcp-reference has no file behind it and a deep link would
  // render the map instead of the docs. Every route here is a real .html file.
  cleanUrls: false,

  // Left at the default (false) on purpose: because of that same catch-all, a dead
  // link in production renders the dashboard rather than announcing itself. The
  // build is the only place it can be caught.
  ignoreDeadLinks: false,

  // Working notes for whoever edits the code. Public in the repository, not on the
  // site — see "One plan doc is published; three are not" in docs-site-plan.md.
  srcExclude: ['docs-site-plan.md', 'nrt-integration-plan.md', 'actris-metadata-api-plan.md'],

  head: [['link', { rel: 'icon', href: `${BASE}favicon.ico` }]],

  vite: { plugins: [planDocPreamble()], build: { cssCodeSplit: true } },

  themeConfig: {
    nav: [
      { text: 'Connect an agent', link: '/mcp-getting-started' },
      { text: 'MCP reference', link: '/mcp-reference' },
      { text: 'REST API', link: '/api' },
      { text: 'Design notes', link: '/mcp-server-plan' },
      { text: 'Dashboard ↗', link: APP },
    ],

    sidebar: [
      {
        text: 'Model Context Protocol',
        items: [
          { text: 'Connecting a client', link: '/mcp-getting-started' },
          { text: 'Tools, resources and prompts', link: '/mcp-reference' },
        ],
      },
      {
        text: 'REST API',
        items: [{ text: 'Endpoint reference', link: '/api' }],
      },
      {
        text: 'Design notes',
        items: [{ text: 'MCP server plan', link: '/mcp-server-plan' }],
      },
    ],

    // Client-side MiniSearch. No account, no external request — which matters for
    // a site whose whole premise is that it costs nothing to run.
    search: { provider: 'local' },

    socialLinks: [{ icon: 'github', link: REPO }],

    outline: { level: [2, 3] },

    footer: {
      message: `Data from <a href="https://ebas.nilu.no">EBAS</a> / <a href="https://www.actris.eu">ACTRIS</a>. Measurements are contributed by station principal investigators — please cite them. MCP endpoint: <code>${MCP}</code>`,
      copyright: `<a href="${REPO}">Source on GitHub</a>`,
    },
  },
})
