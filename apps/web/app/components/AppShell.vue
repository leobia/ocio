<script setup lang="ts">
defineProps<{ section: string, back?: boolean }>()
const route = useRoute()
const links = computed(() => [
  { label: 'Incarichi', icon: 'i-lucide-briefcase-business', to: '/incarichi', active: route.path.startsWith('/incarichi') },
  { label: 'Qualità', to: '/qualita', icon: 'i-lucide-check' },
  { label: 'Modelli', icon: 'i-lucide-files', to: '/modelli', active: route.path === '/modelli' },
  { label: 'Assistente', icon: 'i-lucide-message-square-text', to: '/', active: route.path === '/' },
])
</script>

<template>
  <div class="min-h-screen bg-default text-default lg:grid lg:grid-cols-[240px_minmax(0,1fr)]">
    <aside class="flex flex-col gap-4 border-b border-default bg-muted p-4 lg:sticky lg:top-0 lg:h-dvh lg:border-r lg:border-b-0">
      <NuxtLink to="/incarichi" class="flex items-center gap-2 font-semibold"><UIcon name="i-lucide-shield-check" class="size-6 text-primary" />OCIO</NuxtLink>
      <UNavigationMenu :items="links" orientation="vertical" />
      <slot name="sidebar" />
      <p class="mt-auto text-sm text-muted">Alpha interna · usa solo casi fittizi</p>
    </aside>
    <main class="min-w-0">
      <header class="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-default px-4 py-3 sm:px-6">
        <div class="flex items-center gap-2"><UButton v-if="back" to="/incarichi" icon="i-lucide-arrow-left" color="neutral" variant="ghost" aria-label="Torna agli incarichi" /><h1 class="text-lg font-semibold">{{ section }}</h1></div>
        <slot name="actions" />
      </header>
      <slot />
    </main>
  </div>
</template>
