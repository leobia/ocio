<script setup lang="ts">
// PROTOTYPE — Issue #24 workflow on the existing /incarichi route; switch layouts with ?screen=&variant=.
useHead({ title: 'Prototipi incarichi — OCIO', htmlAttrs: { lang: 'it' } })
const route = useRoute()
const validScreens = ['detail', 'create', 'templates', 'migration'] as const
const screen = computed(() => validScreens.find(item => item === route.query.screen) || 'list')
const variant = computed(() => ['A', 'B', 'C'].includes(String(route.query.variant)) ? String(route.query.variant) : 'A')
const names: Record<string, { key: string, name: string }[]> = {
  detail: [{ key: 'A', name: 'Documento e contesto' }, { key: 'B', name: 'Sezioni guidate' }, { key: 'C', name: 'Revisione ed evidenze' }],
  create: [{ key: 'A', name: 'Modulo compatto' }, { key: 'B', name: 'Percorso guidato' }, { key: 'C', name: 'Contesto e modello' }],
  templates: [{ key: 'A', name: 'Editor affiancato' }, { key: 'B', name: 'Sezioni e indicazioni' }, { key: 'C', name: 'Sezioni e guida per l’agente' }],
  migration: [{ key: 'A', name: 'Confronto per sezioni' }, { key: 'B', name: 'Documento affiancato' }, { key: 'C', name: 'Riepilogo decisionale' }],
}
const assignments = [
  { company: 'Officine Bianchi', initials: 'OB', site: 'Torino · Stabilimento nord', template: 'Fascicolo sicurezza aziendale', revision: 3, updated: 'Oggi, 09:42', progress: 72, migration: true, tone: 'forest' },
  { company: 'Alba Logistica', initials: 'AL', site: 'Novara · Hub intermodale', template: 'Fascicolo sicurezza aziendale', revision: 2, updated: 'Ieri, 16:18', progress: 48, migration: false, tone: 'clay' },
  { company: 'Edilnova Group', initials: 'EG', site: 'Milano · Cantiere Porta Sud', template: 'Fascicolo cantiere', revision: 1, updated: '26 set, 11:05', progress: 31, migration: false, tone: 'ink' },
  { company: 'Verde Comune', initials: 'VC', site: 'Asti · Centro operativo', template: 'Fascicolo servizi', revision: 4, updated: '24 set, 14:30', progress: 89, migration: true, tone: 'olive' },
]
</script>

<template>
  <EngagementPrototypeA v-if="screen === 'list'" :assignments="assignments" />
  <EngagementDetailPrototypeA v-else-if="screen === 'detail' && variant === 'A'" />
  <EngagementDetailPrototypeB v-else-if="screen === 'detail' && variant === 'B'" />
  <EngagementDetailPrototypeC v-else-if="screen === 'detail'" />
  <WorkflowPrototype v-else :screen="screen" :variant="variant" />
  <PrototypeSwitcher v-if="screen !== 'list'" :current="variant" :variants="names[screen] || []" />
</template>
