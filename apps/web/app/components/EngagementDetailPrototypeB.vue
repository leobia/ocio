<script setup lang="ts">
const section = ref('Valutazione dei rischi')
const sections = ['Anagrafica e organizzazione', 'Valutazione dei rischi', 'Procedure operative', 'Emergenze', 'Formazione', 'Sorveglianza sanitaria', 'DPI', 'Macchine e impianti']
const content = reactive<Record<string, string>>({ 'Valutazione dei rischi': 'Il DVR generale è stato acquisito. La valutazione rumore richiede un aggiornamento relativo alla nuova linea produttiva.', 'Anagrafica e organizzazione': 'Officine Bianchi S.r.l. — Stabilimento nord, Torino.' })
</script>

<template>
  <PrototypeShell section="Compilazione per sezioni" back>
    <template #actions><UButton color="neutral" variant="outline" label="Vedi Markdown" to="/incarichi?screen=detail&variant=A" /></template>
    <div class="grid items-start gap-6 p-4 pb-28 sm:p-6 sm:pb-28 xl:grid-cols-[240px_minmax(0,1fr)_260px]">
      <UCard><template #header><h2 class="font-semibold">Sezioni</h2></template><div class="flex flex-col items-start gap-2"><UButton v-for="(item, index) in sections" :key="item" :variant="section === item ? 'soft' : 'ghost'" :aria-current="section === item ? 'page' : undefined" @click="section = item">{{ index + 1 }}. {{ item }}</UButton></div></UCard>
      <UCard>
        <template #header><h2 class="text-xl font-semibold">{{ section }}</h2></template>
        <div class="space-y-6">
          <UFormField label="Contenuto della sezione" description="Ogni sezione mantiene il proprio testo durante l’anteprima."><UTextarea v-model="content[section]" :rows="12" class="w-full" placeholder="Inserisci il contenuto…" /></UFormField>
          <UAlert v-if="section === 'Valutazione dei rischi'" title="Indicazioni" description="Elencare solo le valutazioni applicabili e collegare il piano di miglioramento." color="neutral" variant="subtle" />
          <p class="text-sm text-muted">Prototipo locale: nessuna modifica viene salvata.</p>
        </div>
      </UCard>
      <UCard><template #header><h2 class="font-semibold">Evidenze di esempio</h2></template><ul class="space-y-4 break-words text-sm"><li>DVR_generale_2025.pdf · 42 pagine</li><li>Valutazione_vibrazioni.pdf · 18 pagine</li></ul><template #footer><p class="text-sm text-muted">Collega ogni valutazione al documento di origine.</p></template></UCard>
    </div>
  </PrototypeShell>
</template>
