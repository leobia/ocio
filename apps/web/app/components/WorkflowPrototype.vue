<script setup lang="ts">
import TemplateSectionsPrototype from './TemplateSectionsPrototype.vue'

// PROTOTYPE — Compare workflow structures using the default Nuxt UI theme.
const props = defineProps<{ screen: 'create' | 'templates' | 'migration', variant: string }>()
const company = ref('Officine Bianchi S.r.l.')
const site = ref('Stabilimento nord · Torino')
const referenceDate = ref('2026-09-29')
const model = ref('Fascicolo sicurezza aziendale · revisione 3')
const models = ['Fascicolo sicurezza aziendale · revisione 3', 'Schema personalizzato · revisione 1']
const markdown = ref('## Anagrafica e organizzazione\n\n## Valutazione dei rischi\n\n## Procedure operative')
const instruction = ref('Elencare solo le valutazioni applicabili e collegare il piano di miglioramento.')
const step = ref(0)
const selectedSection = ref('Valutazione dei rischi')
const sections = computed(() => markdown.value.split('\n').filter(line => line.startsWith('## ')).map(line => line.slice(3)))
const instructions = reactive<Record<string, string>>({ 'Valutazione dei rischi': instruction.value })
const title = computed(() => ({ create: 'Nuovo incarico', templates: 'Modelli fascicolo', migration: 'Migrazione fascicolo' })[props.screen])
const steps = ['Dati incarico', 'Modello', 'Riepilogo']
const changes = [
  { title: 'Formazione', status: 'Aggiunta', color: 'success' as const, description: 'Nuova sezione con matrice, scadenze e attestati.' },
  { title: 'Procedure operative', status: 'Spostata', color: 'neutral' as const, description: 'Nuova posizione; i quattro paragrafi manuali restano identici.' },
  { title: 'Macchine', status: 'Conservata', color: 'warning' as const, description: 'Rimossa dal modello, conservata con le evidenze nel fascicolo.' },
]
watch(() => [props.screen, props.variant], () => { step.value = 0 })
</script>

<template>
  <PrototypeShell :section="title" back>
    <template #actions><UBadge color="neutral" variant="subtle">Anteprima locale · {{ variant }}</UBadge></template>
    <div class="mx-auto max-w-7xl space-y-6 p-4 pb-28 sm:p-6 sm:pb-28">
      <UAlert title="Prototipo con dati dimostrativi" description="Le modifiche restano in questa anteprima e non vengono salvate." color="neutral" variant="subtle" />

      <template v-if="screen === 'create'">
        <div v-if="variant === 'B'" class="flex flex-wrap gap-2" aria-label="Passaggi">
          <UButton v-for="(label, index) in steps" :key="label" :variant="step === index ? 'solid' : 'outline'" :aria-current="step === index ? 'step' : undefined" @click="step = index">{{ index + 1 }}. {{ label }}</UButton>
        </div>
        <div class="grid items-start gap-6" :class="variant === 'B' ? 'mx-auto max-w-2xl' : 'lg:grid-cols-2'">
          <UCard v-if="variant !== 'B' || step === 0" :class="{ 'lg:order-2': variant === 'C' }">
            <template #header><h2 class="font-semibold">Dati dell’incarico</h2></template>
            <div class="space-y-4">
              <UFormField label="Azienda"><UInput v-model="company" class="w-full" /></UFormField>
              <UFormField label="Sede"><UInput v-model="site" class="w-full" /></UFormField>
              <UFormField label="Riferimento temporale"><UInput v-model="referenceDate" type="date" class="w-full" /></UFormField>
              <UFormField v-if="variant === 'A'" label="Modello e revisione"><USelect v-model="model" :items="models" class="w-full" /></UFormField>
            </div>
          </UCard>
          <UCard v-if="variant === 'C' || (variant === 'B' && step === 1)">
            <template #header><h2 class="font-semibold">Parti dal modello</h2></template>
            <URadioGroup v-model="model" :items="models" />
            <p class="my-4 text-sm text-muted">La revisione scelta viene associata all’incarico. Le revisioni future richiederanno una migrazione esplicita.</p>
            <UButton to="/incarichi?screen=templates&variant=C" variant="link" label="Esplora schema e indicazioni" />
          </UCard>
          <UCard v-if="variant !== 'B' || step === 2" :class="{ 'lg:col-span-2 lg:order-3': variant === 'C' }">
            <template #header><h2 class="font-semibold">Riepilogo</h2></template>
            <dl class="grid gap-4 sm:grid-cols-2">
              <div v-for="(value, label) in { Azienda: company, Sede: site, Data: referenceDate, Modello: model }" :key="label"><dt class="text-sm text-muted">{{ label }}</dt><dd class="break-words">{{ value || '—' }}</dd></div>
            </dl>
            <template #footer><UButton to="/incarichi?screen=detail&variant=A" label="Apri esempio fascicolo" trailing-icon="i-lucide-arrow-right" /></template>
          </UCard>
        </div>
        <div v-if="variant === 'B'" class="mx-auto flex max-w-2xl justify-between gap-4">
          <UButton color="neutral" variant="outline" :disabled="step === 0" @click="step--">Indietro</UButton>
          <UButton :disabled="step === 2" @click="step++">Continua</UButton>
        </div>
      </template>

      <template v-else-if="screen === 'templates'">
        <div class="flex flex-wrap items-center gap-3"><h2 class="text-xl font-semibold">Fascicolo sicurezza aziendale</h2><UBadge variant="subtle">Revisione 3</UBadge></div>
        <TemplateSectionsPrototype v-if="variant === 'C'" />
        <div v-else class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <UCard v-if="variant === 'B'">
            <template #header><h3 class="font-semibold">Sezioni</h3></template>
            <div class="flex flex-col items-start gap-2"><UButton v-for="section in sections" :key="section" :variant="selectedSection === section ? 'soft' : 'ghost'" @click="selectedSection = section">{{ section }}</UButton></div>
          </UCard>
          <UCard v-if="variant === 'B'">
            <template #header><h3 class="font-semibold">{{ selectedSection }}</h3></template>
            <UFormField label="Indicazioni di compilazione" description="Ogni sezione mantiene le proprie indicazioni."><UTextarea v-model="instructions[selectedSection]" :rows="6" class="w-full" /></UFormField>
          </UCard>
          <UCard v-else>
            <template #header><h3 class="font-semibold">Schema Markdown</h3></template>
            <UFormField label="Struttura" description="Usa titoli di secondo livello (##) per le sezioni."><UTextarea v-model="markdown" :rows="10" spellcheck="false" class="w-full" /></UFormField>
            <UFormField class="mt-4" label="Indicazioni · Valutazione dei rischi"><UTextarea v-model="instructions['Valutazione dei rischi']" :rows="3" class="w-full" /></UFormField>
          </UCard>
          <UCard v-if="variant !== 'B'">
            <template #header><h3 class="font-semibold">Anteprima struttura</h3></template>
            <ol class="list-inside list-decimal space-y-4"><li v-for="(section, index) in sections" :key="index">{{ section }}</li></ol>
            <template #footer><p class="text-sm text-muted">Gli incarichi esistenti mantengono la revisione 3 fino all’applicazione di una migrazione.</p></template>
          </UCard>
        </div>
        <div class="flex flex-wrap justify-end gap-3"><UButton color="neutral" variant="outline" to="/incarichi?screen=create&variant=A">Usa il modello</UButton><UButton to="/incarichi?screen=migration&variant=A">Anteprima revisione</UButton></div>
      </template>

      <template v-else>
        <div><h2 class="text-xl font-semibold">Revisione 3 → 4</h2><p class="text-muted">Officine Bianchi · Stabilimento nord, Torino</p></div>
        <div class="grid items-start gap-6" :class="variant === 'C' ? 'lg:grid-cols-[320px_minmax(0,1fr)]' : variant === 'A' ? 'lg:grid-cols-[minmax(0,1fr)_320px]' : ''">
          <UCard v-if="variant === 'B'">
            <template #header><h3 class="font-semibold">Confronto documenti</h3></template>
            <div class="grid gap-6 sm:grid-cols-2">
              <div><UBadge color="neutral" variant="subtle">Attuale · revisione 3</UBadge><div class="mt-4 space-y-4"><p>Procedure operative</p><p class="text-muted">Testo manuale approvato…</p><p>Macchine</p><p class="text-muted">Evidenze collegate…</p></div></div>
              <div><UBadge variant="subtle">Proposta · revisione 4</UBadge><div class="mt-4 space-y-4"><p class="text-success">Formazione · nuova sezione</p><p>Procedure operative</p><p class="text-muted">Testo manuale approvato…</p><p>Appendice: Macchine ed evidenze conservate</p></div></div>
            </div>
          </UCard>
          <div class="space-y-4" :class="{ 'lg:order-2': variant === 'C' }">
            <UCard v-for="change in changes" :key="change.title">
              <template #header><div class="flex flex-wrap items-center justify-between gap-3"><h3 class="font-semibold">{{ change.title }}</h3><UBadge :color="change.color" variant="subtle">{{ change.status }}</UBadge></div></template>
              <p>{{ change.description }}</p>
            </UCard>
          </div>
          <UCard :class="{ 'lg:order-1': variant === 'C' }">
            <template #header><h3 class="font-semibold">Prima di applicare</h3></template>
            <ul class="space-y-3"><li v-for="item in ['Testo manuale conservato', 'Fatti ed evidenze conservati', 'Sezioni rimosse recuperabili']" :key="item" class="flex items-start gap-2"><UIcon name="i-lucide-check" class="mt-1 shrink-0 text-success" />{{ item }}</li></ul>
            <p class="mt-4 text-sm text-muted">La proposta resta separata dal fascicolo fino alla conferma dell’operatore.</p>
            <template #footer><UButton to="/incarichi?screen=detail&variant=A" color="neutral" variant="outline">Torna all’esempio fascicolo</UButton></template>
          </UCard>
        </div>
      </template>
    </div>
  </PrototypeShell>
</template>
