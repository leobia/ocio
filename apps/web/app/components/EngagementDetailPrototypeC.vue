<script setup lang="ts">
const tab = ref('document')
const tabs = [{ label: 'Contenuti', value: 'document' }, { label: 'Evidenze', value: 'evidence' }, { label: 'Revisione', value: 'revision' }]
const note = ref('')
</script>

<template>
  <PrototypeShell section="Revisione ed evidenze" back>
    <template #actions><UBadge color="neutral" variant="subtle">Anteprima locale</UBadge></template>
    <div class="mx-auto max-w-5xl space-y-6 p-4 pb-28 sm:p-6 sm:pb-28">
      <div><h2 class="text-xl font-semibold">Officine Bianchi</h2><p class="text-muted">Stabilimento nord · Torino · revisione 3</p></div>
      <UTabs v-model="tab" :items="tabs" :content="false" />
      <UCard v-if="tab === 'document'">
        <template #header><h3 class="font-semibold">Contenuti da verificare</h3></template>
        <div class="space-y-6"><div><UBadge variant="subtle">Anagrafica completa</UBadge><p class="mt-3">RSPP e RLS confermati; nomina del medico competente da verificare.</p></div><div><UBadge color="warning" variant="subtle">Valutazione dei rischi</UBadge><p class="mt-3">Il DVR generale è acquisito. La valutazione rumore richiede un aggiornamento per la nuova linea produttiva.</p></div><UFormField label="Nota di revisione locale"><UTextarea v-model="note" :rows="4" class="w-full" /></UFormField></div>
      </UCard>
      <UCard v-else-if="tab === 'evidence'">
        <template #header><h3 class="font-semibold">Evidenze di esempio</h3></template>
        <ul class="space-y-4"><li>DVR generale 2025 · acquisito</li><li>Valutazione vibrazioni · corrente</li><li>Valutazione rumore · da aggiornare</li></ul>
      </UCard>
      <UCard v-else>
        <template #header><h3 class="font-semibold">Revisione 4 disponibile</h3></template>
        <p>Nuova sezione Formazione, riordino delle Procedure operative e conservazione della sezione Macchine.</p>
        <template #footer><UButton to="/incarichi?screen=migration&variant=A">Confronta la proposta</UButton></template>
      </UCard>
      <p class="text-sm text-muted">Prototipo con dati dimostrativi. Le note non vengono salvate.</p>
    </div>
  </PrototypeShell>
</template>
