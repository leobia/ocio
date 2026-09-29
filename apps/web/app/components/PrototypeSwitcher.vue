<script setup lang="ts">
const props = defineProps<{ current: string, variants: { key: string, name: string }[] }>()
const route = useRoute()
const router = useRouter()
const isDev = import.meta.dev

function move(offset: number) {
  const index = props.variants.findIndex(item => item.key === props.current)
  const next = props.variants[(index + offset + props.variants.length) % props.variants.length]!
  void router.replace({ query: { ...route.query, variant: next.key } })
}

function onKeydown(event: KeyboardEvent) {
  if (['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName) || (event.target as HTMLElement).isContentEditable) return
  if (event.key === 'ArrowLeft') move(-1)
  if (event.key === 'ArrowRight') move(1)
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div v-if="isDev" class="prototype-switcher" aria-label="Selettore prototipo">
    <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-left" aria-label="Variante precedente" @click="move(-1)" />
    <div><small>PROTOTIPO UI</small><strong>{{ current }} — {{ variants.find(item => item.key === current)?.name }}</strong></div>
    <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-right" aria-label="Variante successiva" @click="move(1)" />
  </div>
</template>

<style scoped>
.prototype-switcher{position:fixed;z-index:100;bottom:1.1rem;left:50%;display:flex;align-items:center;gap:.45rem;padding:.35rem;transform:translateX(-50%);border:1px solid #ffffff24;border-radius:999px;color:white;background:#17211df2;box-shadow:0 14px 40px #0004;backdrop-filter:blur(12px)}.prototype-switcher>div{display:grid;min-width:13rem;padding:0 .7rem;text-align:center}.prototype-switcher small{color:#9fb2a8;font-size:.52rem;font-weight:700;letter-spacing:.14em}.prototype-switcher strong{font-size:.72rem;font-weight:600}
</style>
