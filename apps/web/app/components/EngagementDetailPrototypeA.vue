<script setup lang="ts">
const text = ref(`# Fascicolo sicurezza aziendale

## 1. Anagrafica e organizzazione

Officine Bianchi S.r.l. — Stabilimento nord, Torino.

- RSPP: incarico confermato
- RLS: documentazione acquisita
- Medico competente: nomina da verificare

## 2. Valutazione dei rischi

Il DVR generale è stato acquisito. La valutazione rumore richiede un aggiornamento relativo alla nuova linea produttiva.

## 3. Procedure operative

- Procedura manutenzione presse
- Gestione DPI e consegne`)
</script>

<template>
  <PrototypeShell section="Fascicolo" back>
    <template #actions><UBadge color="neutral" variant="subtle">Anteprima locale</UBadge></template>
    <div class="grid items-start gap-6 p-4 pb-28 sm:p-6 sm:pb-28 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div class="min-w-0 space-y-6">
        <UAlert title="Revisione 4 disponibile" description="Confronta la proposta prima di applicarla." color="warning" variant="subtle" :actions="[{ label: 'Confronta', to: '/incarichi?screen=migration&variant=A', color: 'warning', variant: 'outline' }]" />
        <UCard>
          <template #header><h2 class="text-xl font-semibold">Officine Bianchi</h2><p class="text-muted">Stabilimento nord · Torino</p></template>
          <UFormField label="Fascicolo Markdown" description="Modifiche locali: questa anteprima non salva il documento."><UTextarea v-model="text" :rows="22" class="w-full" spellcheck="false" /></UFormField>
        </UCard>
      </div>
      <aside class="space-y-6">
        <UCard><template #header><h2 class="font-semibold">Incarico</h2></template><dl class="space-y-4"><div><dt class="text-sm text-muted">Modello</dt><dd>Fascicolo sicurezza aziendale</dd></div><div><dt class="text-sm text-muted">Revisione</dt><dd>3</dd></div><div><dt class="text-sm text-muted">Riferimento</dt><dd>29 settembre 2026</dd></div></dl></UCard>
        <UCard><template #header><h2 class="font-semibold">Stato dimostrativo</h2></template><UProgress :model-value="72" status /><p class="mt-4 text-sm text-muted">Formazione da completare</p></UCard>
        <UAlert title="Valutazione dei rischi" description="Elencare solo le valutazioni applicabili e collegare il piano di miglioramento." color="neutral" variant="subtle" />
      </aside>
    </div>
  </PrototypeShell>
</template>
