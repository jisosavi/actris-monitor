<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { Button } from '@/components/ui/button'
import { useStationsStore } from '@/stores/stations'

const store = useStationsStore()
const { showDataSetup } = storeToRefs(store)
</script>

<template>
  <div class="admin-panel">
    <Button size="sm" variant="outline" class="setup-btn" @click="showDataSetup = true">
      Data Setup
    </Button>
  </div>
</template>

<style scoped>
.admin-panel { padding: 12px 16px; }
.setup-btn { width: 100%; font-size: 11px; }
</style>
