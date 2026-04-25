<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useFetchProgress } from '@/composables/useStationData'

const props = defineProps<{ fullScreen: boolean }>()

const { data: job } = useFetchProgress()

const pct = computed(() => {
  if (!job.value || job.value.total === 0) return 0
  return Math.round((job.value.done / job.value.total) * 100)
})

const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  timer = setInterval(() => {
    if (!job.value?.started_at) return
    elapsed.value = Math.floor((Date.now() - new Date(job.value.started_at).getTime()) / 1000)
  }, 1000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })

function fmtElapsed(s: number) {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}m ${sec}s`
}

const statusLabel = computed(() => {
  switch (job.value?.status) {
    case 'running': return 'Fetching…'
    case 'complete': return 'Complete'
    case 'complete_with_errors': return 'Done (some errors)'
    case 'failed': return 'Failed'
    default: return ''
  }
})
</script>

<template>
  <!-- Full-screen overlay (first-run) -->
  <div v-if="fullScreen" class="fs-overlay">
    <div class="fs-box">
      <div class="fs-title">Loading data…</div>
      <div class="progress-wrap">
        <div class="progress-bar" :style="{ width: pct + '%' }" />
      </div>
      <div class="progress-numbers">{{ job?.done ?? 0 }} / {{ job?.total ?? 0 }} combinations</div>
      <div class="progress-desc">{{ job?.current_desc ?? '' }}</div>
      <div class="progress-elapsed">Elapsed: {{ fmtElapsed(elapsed) }}</div>
      <div v-if="job?.error_msg" class="progress-error">{{ job.error_msg }}</div>
      <div class="fs-note">You can close this overlay — fetching continues in the background.</div>
    </div>
  </div>

  <!-- Inline panel (admin panel) -->
  <div v-else class="inline-progress">
    <div class="inline-header">
      <span class="inline-status" :class="`status--${job?.status ?? 'idle'}`">{{ statusLabel }}</span>
      <span class="inline-elapsed">{{ fmtElapsed(elapsed) }}</span>
    </div>
    <div class="progress-wrap">
      <div class="progress-bar" :style="{ width: pct + '%' }" />
    </div>
    <div class="progress-numbers">{{ job?.done ?? 0 }} / {{ job?.total ?? 0 }}</div>
    <div class="progress-desc">{{ job?.current_desc ?? '' }}</div>
    <div v-if="job?.error_msg" class="progress-error">{{ job.error_msg }}</div>
  </div>
</template>

<style scoped>
/* ── Full-screen ── */
.fs-overlay {
  position: fixed;
  inset: 0;
  background: rgba(238, 241, 247, 0.92);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 400;
  backdrop-filter: blur(4px);
}
.fs-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 32px 36px;
  max-width: 420px;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 8px 32px rgba(48, 49, 147, 0.12);
}
.fs-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
}
.fs-note {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
  margin-top: 4px;
}

/* ── Inline ── */
.inline-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 0;
}
.inline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.inline-status {
  font-size: 11px;
  font-weight: 600;
}
.status--running  { color: var(--accent); }
.status--complete { color: var(--positive); }
.status--failed, .status--complete_with_errors { color: var(--negative); }
.inline-elapsed {
  font-size: 10px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

/* ── Shared ── */
.progress-wrap {
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
}
.progress-bar {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width 0.4s ease;
}
.progress-numbers {
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
}
.progress-desc {
  font-size: 11px;
  color: var(--text-muted);
  word-break: break-all;
}
.progress-elapsed {
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.progress-error {
  font-size: 11px;
  color: var(--negative);
}
</style>
