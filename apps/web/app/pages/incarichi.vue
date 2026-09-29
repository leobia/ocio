<script setup lang="ts">
// PROTOTYPE — Chosen index plus three engagement-detail variants via ?screen=detail&variant=.
useHead({ title: 'Prototipi incarichi — OCIO', htmlAttrs: { lang: 'it' } })
const route = useRoute()
const variants = [
  { key: 'A', name: 'Cockpit operativo' },
  { key: 'B', name: 'Portfolio aziende' },
  { key: 'C', name: 'Studio documento' },
]
const variant = computed(() => variants.some(item => item.key === route.query.variant) ? String(route.query.variant) : 'A')
const detail = computed(() => route.query.screen === 'detail')
const assignments = [
  { company: 'Officine Bianchi', initials: 'OB', site: 'Torino · Stabilimento nord', template: 'Fascicolo sicurezza aziendale', revision: 3, updated: 'Oggi, 09:42', progress: 72, migration: true, tone: 'forest' },
  { company: 'Alba Logistica', initials: 'AL', site: 'Novara · Hub intermodale', template: 'Fascicolo sicurezza aziendale', revision: 2, updated: 'Ieri, 16:18', progress: 48, migration: false, tone: 'clay' },
  { company: 'Edilnova Group', initials: 'EG', site: 'Milano · Cantiere Porta Sud', template: 'Fascicolo cantiere', revision: 1, updated: '26 set, 11:05', progress: 31, migration: false, tone: 'ink' },
  { company: 'Verde Comune', initials: 'VC', site: 'Asti · Centro operativo', template: 'Fascicolo servizi', revision: 4, updated: '24 set, 14:30', progress: 89, migration: true, tone: 'olive' },
]
</script>

<template>
  <EngagementPrototypeA v-if="!detail" :assignments="assignments" />
  <EngagementDetailPrototypeA v-else-if="variant === 'A'" />
  <EngagementDetailPrototypeB v-else-if="variant === 'B'" />
  <EngagementDetailPrototypeC v-else />
  <PrototypeSwitcher v-if="detail" :current="variant" :variants="[
    { key: 'A', name: 'Documento e contesto' },
    { key: 'B', name: 'Sezioni guidate' },
    { key: 'C', name: 'Revisione ed evidenze' },
  ]" />
</template>
