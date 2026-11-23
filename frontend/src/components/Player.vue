<script setup lang="ts">
import videojs from 'video.js'
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{ src: string }>()
const emit = defineEmits<{ time: [ms: number]; error: [] }>()

const el = ref<HTMLVideoElement>()
let player: ReturnType<typeof videojs> | null = null
let stopAt: number | null = null   // 播放到片段终点就停

onMounted(() => {
  player = videojs(el.value!, {
    controls: true, preload: 'auto', fluid: false, fill: true, playbackRates: [0.75, 1, 1.25, 1.5, 2],
    controlBar: { pictureInPictureToggle: false },
    sources: [{ src: props.src, type: 'application/x-mpegURL' }],
  })
  player.on('timeupdate', () => {
    const t = (player!.currentTime() ?? 0) * 1000
    emit('time', t)
    if (stopAt != null && t >= stopAt) {
      stopAt = null
      player!.pause()
    }
  })
  player.on('seeking', () => emit('time', (player!.currentTime() ?? 0) * 1000))
  player.on('error', () => emit('error'))
})
onBeforeUnmount(() => player?.dispose())

function seek(ms: number, play = true) {
  if (!player) return
  stopAt = null
  player.currentTime(ms / 1000)
  if (play) player.play()?.catch(() => {})
}
function playRange(startMs: number, endMs: number) {
  if (!player) return
  player.currentTime(startMs / 1000)
  stopAt = endMs
  player.play()?.catch(() => {})
}
defineExpose({ seek, playRange })
</script>

<template>
  <div class="frame"><video ref="el" class="video-js vjs-big-play-centered" playsinline /></div>
</template>

<style scoped>
.frame { position: relative; width: 100%; aspect-ratio: 16 / 9; background: #0b0f14; border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); }
.frame :deep(.video-js) { font-family: var(--font); }
.frame :deep(.vjs-big-play-button) { border-radius: 50%; width: 64px; height: 64px; line-height: 62px; margin: -32px 0 0 -32px; border-width: 2px; background: rgba(11, 15, 20, .55); }
.frame :deep(.vjs-play-progress), .frame :deep(.vjs-volume-level) { background: #6cc0e5; }
</style>
