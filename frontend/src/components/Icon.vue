<script setup lang="ts">
defineProps<{ name: keyof typeof paths }>()
</script>

<script lang="ts">
const paths = {
  play: 'M5 3.5v9l7.5-4.5z',
  check: 'M3.5 8.5l3 3 6-7',
  edit: 'M10.8 2.7l2.5 2.5M2.8 13.2l.6-3 7.4-7.5 2.5 2.5-7.5 7.4z',
  trash: 'M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.5 8.5h6l.5-8.5',
  plus: 'M8 3v10M3 8h10',
  back: 'M9.5 3.5L5 8l4.5 4.5',
  upload: 'M8 10.5V3M5 5.5L8 2.5l3 3M3 10.5v2.5h10v-2.5',
  refresh: 'M12.5 6A5 5 0 1 0 13 9M12.5 2.5V6H9',
  doc: 'M4 2.5h5.5L12 5v8.5H4zM9.5 2.5V5H12M6 8h4M6 10.5h4',
  undo: 'M5.5 3.5L3 6l2.5 2.5M3 6h6a3.5 3.5 0 0 1 0 7H6.5',
  download: 'M8 2.5v7.5M5 7l3 3 3-3M3 12.5h10',
  send: 'M2.5 8l10.5-5-4 10-2-4z',
}
</script>

<template>
  <svg class="icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"
       stroke-linejoin="round" aria-hidden="true">
    <path :d="paths[name]" :fill="name === 'play' ? 'currentColor' : 'none'" />
  </svg>
</template>
