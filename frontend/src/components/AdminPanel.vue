<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { useStationsStore } from '@/stores/stations'

const store = useStationsStore()
const { showDataSetup } = storeToRefs(store)

// Absolute rather than derived from import.meta.env.BASE_URL: the docs are a
// separate build that only exists on the deployed host, so a relative link would
// 404 during `npm run dev` and look like a bug in the dialog.
const DOCS_URL = 'https://www.isosavi.com/test/actris-monitor/docs/'
const REPOSITORY_URL = 'https://github.com/jisosavi/actris-monitor'
</script>

<template>
  <div class="admin-panel">
    <Button size="sm" variant="outline" class="panel-btn" @click="showDataSetup = true">
      Data Setup
    </Button>
    <!-- A dialog rather than a third button: the scoped style below records that
         two stacked buttons already overflow this sidebar on a short window. -->
    <Dialog>
      <DialogTrigger as-child>
        <Button size="sm" variant="outline" class="panel-btn">
          About this app
        </Button>
      </DialogTrigger>
      <DialogContent class="about-dialog">
        <DialogHeader>
          <DialogTitle>ACTRIS Monitor</DialogTitle>
          <DialogDescription>
            Annual-mean in-situ aerosol measurements from the EBAS/ACTRIS European
            research network. Level 2 quality-assured data, 2000 onwards.
          </DialogDescription>
        </DialogHeader>

        <div class="about-links">
          <a class="about-link" :href="DOCS_URL" target="_blank" rel="noopener noreferrer">
            <span class="about-link-title">Documentation ↗</span>
            <span class="about-link-sub">
              How the data is built and what it does not say, plus the MCP endpoint
              and REST API reference for querying it yourself.
            </span>
          </a>
          <a class="about-link" :href="REPOSITORY_URL" target="_blank" rel="noopener noreferrer">
            <span class="about-link-title">Source on GitHub ↗</span>
            <span class="about-link-sub">
              The code behind the dashboard, the backend and the MCP server — and
              where to raise an issue.
            </span>
          </a>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<style scoped>
.about-links { display: flex; flex-direction: column; gap: 10px; margin-top: 4px; }

.about-link {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 13px;
  border: 1px solid var(--border);
  border-radius: 8px;
  text-decoration: none;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.about-link:hover { border-color: var(--accent); background: var(--accent-light); }

.about-link-title { font-size: 13px; font-weight: 600; color: var(--accent); }
.about-link-sub { font-size: 12px; line-height: 1.45; color: var(--text-muted); }

/* Pinned to the bottom of the scrolling sidebar. Two stacked buttons push the
   sidebar's content past its height on a 1000px window, and without this both
   scroll out of sight — including Data Setup, which used to be visible. */
.admin-panel {
  position: sticky;
  bottom: 0;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--surface);
  border-top: 1px solid var(--border);
}
.panel-btn { width: 100%; font-size: 11px; }
/* The second button is an anchor, which does not inherit the button's centring. */
a.panel-btn { display: inline-flex; align-items: center; justify-content: center; text-decoration: none; }
</style>
