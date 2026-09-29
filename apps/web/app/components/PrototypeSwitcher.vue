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
  const target = event.target as HTMLElement
  if (event.defaultPrevented || target.closest('input, textarea, select, button, [role=tablist], [role=combobox], [role=listbox], [contenteditable]')) return
  if (event.key === 'ArrowLeft') move(-1)
  if (event.key === 'ArrowRight') move(1)
}

onMounted(() => { if (isDev) window.addEventListener('keydown', onKeydown) })
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div v-if="isDev" class="fixed bottom-4 left-1/2 z-50 flex w-max max-w-[calc(100%-2rem)] -translate-x-1/2 items-center gap-2 rounded-lg border border-default bg-elevated p-2 shadow-lg" aria-label="Selettore prototipo">
    <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-left" aria-label="Variante precedente" @click="move(-1)" />
    <div class="min-w-0 text-center"><p class="text-xs text-muted">Prototipo UI</p><p class="text-sm font-medium">{{ current }} — {{ variants.find(item => item.key === current)?.name }}</p></div>
    <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-right" aria-label="Variante successiva" @click="move(1)" />
  </div>
</template>
