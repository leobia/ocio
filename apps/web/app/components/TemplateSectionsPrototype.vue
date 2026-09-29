<script setup lang="ts">
// PROTOTYPE — A template is an ordered list of sections, each with agent guidance.
let nextId = 4
const sections = ref([
  { id: 1, title: 'Anagrafica e organizzazione', instruction: 'Riporta azienda, sede e figure della sicurezza. Segnala le nomine mancanti senza inventare dati.' },
  { id: 2, title: 'Valutazione dei rischi', instruction: 'Elenca le valutazioni applicabili alla sede. Collega le evidenze disponibili e indica gli aggiornamenti necessari.' },
  { id: 3, title: 'Procedure operative', instruction: 'Descrivi le procedure documentate per le attività della sede. Distingui quelle approvate da quelle ancora da verificare.' },
])
const markdown = computed(() => sections.value.map(section => `## ${section.title.trim() || 'Sezione senza titolo'}`).join('\n\n'))
const preview = ref(false)

async function addSection() {
  const id = nextId++
  sections.value.push({ id, title: '', instruction: '' })
  await nextTick()
  document.getElementById(`section-title-${id}`)?.focus()
}

function move(index: number, offset: number) {
  const target = index + offset
  if (target < 0 || target >= sections.value.length) return
  const [section] = sections.value.splice(index, 1)
  if (section) sections.value.splice(target, 0, section)
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6">
    <div class="space-y-2">
      <h3 class="text-lg font-semibold">Sezioni del fascicolo</h3>
      <p class="text-muted">Definisci le sezioni nell’ordine desiderato. Per ciascuna, spiega all’agente cosa cercare e come compilare il contenuto.</p>
    </div>

    <UCard v-for="(section, index) in sections" :key="section.id" as="section" :aria-label="`Sezione ${index + 1}`">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h4 class="font-semibold">Sezione {{ index + 1 }}</h4>
          <div class="flex gap-1">
            <UButton icon="i-lucide-arrow-up" color="neutral" variant="ghost" :disabled="index === 0" :aria-label="`Sposta su sezione ${index + 1}`" @click="move(index, -1)" />
            <UButton icon="i-lucide-arrow-down" color="neutral" variant="ghost" :disabled="index === sections.length - 1" :aria-label="`Sposta giù sezione ${index + 1}`" @click="move(index, 1)" />
            <UButton icon="i-lucide-trash-2" color="neutral" variant="ghost" :aria-label="`Rimuovi sezione ${index + 1}`" @click="sections.splice(index, 1)" />
          </div>
        </div>
      </template>
      <div class="space-y-4">
        <UFormField label="Titolo della sezione" :name="`section-title-${section.id}`">
          <UInput :id="`section-title-${section.id}`" v-model="section.title" class="w-full" placeholder="Es. Formazione e addestramento" />
        </UFormField>
        <UFormField label="Indicazioni per l’agente" description="Indica contenuti attesi, fonti da usare e cosa fare se mancano informazioni.">
          <UTextarea v-model="section.instruction" :rows="3" class="w-full" placeholder="Es. Elenca la formazione richiesta per ogni mansione, collega gli attestati e segnala le scadenze da verificare." />
        </UFormField>
      </div>
    </UCard>

    <p v-if="!sections.length" class="text-muted">Il modello non ha ancora sezioni. Aggiungi la prima per iniziare.</p>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <UButton icon="i-lucide-plus" label="Aggiungi sezione" @click="addSection" />
      <UButton color="neutral" variant="outline" :aria-expanded="preview" @click="preview = !preview">{{ preview ? 'Nascondi anteprima' : 'Anteprima modello' }}</UButton>
    </div>

    <UCard v-if="preview">
      <template #header><h3 class="font-semibold">Anteprima modello</h3></template>
      <div class="space-y-6">
        <div v-for="section in sections" :key="section.id" class="space-y-2">
          <h4 class="font-semibold">{{ section.title || 'Sezione senza titolo' }}</h4>
          <p class="whitespace-pre-wrap text-sm text-muted">{{ section.instruction || 'Nessuna indicazione per l’agente.' }}</p>
        </div>
        <details class="border-t border-default pt-4"><summary class="cursor-pointer text-sm text-muted">Schema Markdown generato</summary><pre class="mt-3 whitespace-pre-wrap break-words text-sm">{{ markdown }}</pre></details>
      </div>
    </UCard>
  </div>
</template>
