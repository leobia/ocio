<script setup lang="ts">
// PROTOTYPE — The same fictional conversation makes each layout comparable without an API.
const props = defineProps<{ variant: string }>()
const draft = ref('')
const showContext = ref(false)
const variants = [{ key: 'A', name: 'Scrivania a tre colonne' }, { key: 'B', name: 'Conversazione focalizzata' }, { key: 'C', name: 'Contesto sopra il dialogo' }]
const facts = [
  { name: 'Azienda', value: 'Officine Bianchi', note: 'Caso fittizio' },
  { name: 'Sede', value: 'Stabilimento nord · Torino', note: '12 lavoratori' },
  { name: 'Documenti disponibili', value: 'DVR generale · Piano formazione', note: 'Attestati da verificare' },
]
watch(() => props.variant, () => { showContext.value = false })
</script>

<template>
  <PrototypeShell section="Assistente normativo">
    <template #sidebar>
      <p class="text-sm text-muted">Conversazione di esempio</p>
      <p class="font-medium">Verifica della formazione</p>
    </template>
    <template #actions><UButton to="/?mode=live" color="neutral" variant="outline">Apri assistente reale</UButton></template>
    <div class="space-y-6 p-4 pb-28 sm:p-6 sm:pb-28">
      <UAlert title="Anteprima con dati dimostrativi" description="Lo stesso caso nelle tre disposizioni. Il testo scritto qui non viene inviato né salvato." color="neutral" variant="subtle" />
      <div class="grid items-start gap-6" :class="variant === 'A' ? 'lg:grid-cols-[minmax(0,1fr)_280px]' : variant === 'B' ? 'mx-auto max-w-2xl' : 'mx-auto max-w-5xl'">
        <UCard v-if="variant !== 'B' || showContext" as="aside" aria-label="Contesto dimostrativo" :class="variant === 'A' ? 'order-2' : 'order-1'">
          <template #header><h2 class="font-semibold">Dati del caso</h2></template>
          <dl class="grid gap-6" :class="variant === 'C' ? 'sm:grid-cols-3' : ''">
            <div v-for="fact in facts" :key="fact.name" class="space-y-1"><dt class="text-sm text-muted">{{ fact.name }}</dt><dd>{{ fact.value }}</dd><dd class="text-sm text-muted">{{ fact.note }}</dd></div>
          </dl>
        </UCard>
        <div class="min-w-0 space-y-6" :class="variant === 'A' ? 'order-1' : 'order-2'">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h2 class="text-lg font-semibold">Verifica della formazione</h2>
            <UButton v-if="variant === 'B'" color="neutral" variant="outline" :aria-expanded="showContext" @click="showContext = !showContext">{{ showContext ? 'Nascondi dati del caso' : 'Mostra dati del caso' }}</UButton>
          </div>
          <section class="space-y-6" aria-label="Conversazione dimostrativa">
            <div class="ml-auto max-w-[90%] rounded-lg bg-muted p-4"><p>Devo verificare la formazione dei 12 lavoratori dello stabilimento nord. Da quali documenti parto?</p></div>
            <div class="space-y-4">
              <p class="text-sm font-semibold text-primary">OCIO · risposta di esempio</p>
              <p>Possiamo organizzare la verifica confrontando mansioni, piano formativo e attestati disponibili.</p>
              <ul class="list-inside list-disc space-y-2"><li>Associa ogni lavoratore alla mansione indicata.</li><li>Raccogli gli attestati e le relative date.</li><li>Segnala i documenti mancanti per la verifica.</li></ul>
              <UAlert title="Informazione da completare" description="Sono già disponibili gli attestati di tutti i lavoratori?" color="neutral" variant="subtle" />
            </div>
          </section>
          <UCard>
            <UFormField label="Scrivi una domanda" description="Bozza locale per provare la disposizione dei controlli."><UTextarea v-model="draft" :rows="3" class="w-full" placeholder="Chiedi a OCIO…" /></UFormField>
            <template #footer><div class="flex items-center justify-between gap-3"><p class="text-sm text-muted">Invio disponibile nell’assistente reale.</p><UButton disabled icon="i-lucide-arrow-up" aria-label="Invio disabilitato nell’anteprima" /></div></template>
          </UCard>
        </div>
      </div>
    </div>
    <PrototypeSwitcher :current="variant" :variants="variants" />
  </PrototypeShell>
</template>
