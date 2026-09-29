<script setup lang="ts">
import type { Engagement } from '~/types'
definePageMeta({ key: route => String(route.params.id) })
const api = useOcioApi()
const route = useRoute()
// Throwaway #25 UI, available only in development.
const intakePrototype = computed(() => import.meta.dev && ['A', 'B', 'C'].includes(String(route.query.variant)))
const engagement = ref<Engagement | null>(null)
const markdown = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const reviewing = ref(false)
const dirty = computed(() => engagement.value !== null && markdown.value !== engagement.value.dossier_markdown)
useUnsavedChanges(dirty)
useHead({ title: computed(() => `${engagement.value?.company || 'Fascicolo'} — OCIO`), htmlAttrs: { lang: 'it' } })
function accept(result: Engagement) {
  engagement.value = result
  markdown.value = result.dossier_markdown
}
async function load() {
  loading.value = true
  error.value = ''
  try { accept(await api.getEngagement(String(route.params.id))) }
  catch (reason) { error.value = (reason as Error).message }
  finally { loading.value = false }
}
async function save() {
  if (!engagement.value || !dirty.value || saving.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    accept(await api.updateDossier(engagement.value.id, markdown.value))
    // Saving recomputes pending migrations: require reviewing the refreshed proposal.
    reviewing.value = false
    notice.value = 'Versione salvata nella cronologia.'
  }
  catch (reason) { error.value = (reason as Error).message }
  finally { saving.value = false }
}
async function apply() {
  const item = engagement.value
  if (!item?.pending_migration || dirty.value || saving.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    accept(await api.applyMigration(item.id, item.pending_migration.id))
    reviewing.value = false
    notice.value = 'Migrazione applicata. La versione precedente resta nella cronologia.'
  }
  catch (reason) { error.value = (reason as Error).message }
  finally { saving.value = false }
}
onMounted(() => {
  if (!(intakePrototype.value && route.params.id === 'demo')) load()
})
</script>

<template>
  <AppShell section="Fascicolo" back>
    <template #actions><UButton v-if="engagement && !intakePrototype" :loading="saving" :disabled="!dirty || saving" @click="save">Salva fascicolo</UButton></template>
    <PrototypeIntakePrototype v-if="intakePrototype" />
    <div v-else class="space-y-6 p-4 sm:p-6">
      <UAlert v-if="error" role="alert" color="error" :title="error" :actions="!engagement ? [{ label: 'Riprova', onClick: load }] : []" />
      <p v-if="loading" role="status">Caricamento fascicolo…</p>
      <p v-if="notice" role="status" class="text-success">{{ notice }}</p>
      <template v-if="engagement && !loading">
        <div class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div class="min-w-0 space-y-6">
            <UAlert v-if="engagement.pending_migration" color="warning" variant="subtle" :title="`Revisione ${engagement.pending_migration.target_revision} disponibile`" description="Il fascicolo resta sulla revisione corrente finché non applichi la proposta.">
              <template #actions><UButton color="warning" variant="outline" :disabled="saving" @click="reviewing = !reviewing">{{ reviewing ? 'Chiudi confronto' : 'Confronta proposta' }}</UButton></template>
            </UAlert>
            <UCard>
              <template #header><h2 class="text-xl font-semibold">{{ engagement.company }}</h2><p class="text-muted">{{ engagement.site }}</p></template>
              <UFormField label="Fascicolo Markdown" :description="dirty ? 'Modifiche non salvate.' : 'Ogni salvataggio conserva una versione nella cronologia.'"><UTextarea v-model="markdown" :rows="24" :disabled="saving" spellcheck="false" class="w-full" /></UFormField>
            </UCard>
          </div>
          <aside class="space-y-6">
            <UCard>
              <template #header><h2 class="font-semibold">Incarico</h2></template>
              <dl class="space-y-4"><div><dt class="text-sm text-muted">Modello</dt><dd>{{ engagement.template.name }} · revisione {{ engagement.template_revision.number }}</dd></div><div><dt class="text-sm text-muted">Riferimento</dt><dd>{{ engagement.reference_date }}</dd></div><div><dt class="text-sm text-muted">Ultima modifica</dt><dd>{{ new Date(engagement.updated_at).toLocaleString('it-IT') }}</dd></div></dl>
              <template #footer><UButton variant="link" :to="`/modelli?model=${engagement.template.id}&engagement=${engagement.id}`">Modelli fascicolo</UButton></template>
            </UCard>
            <UCard>
              <template #header><h2 class="font-semibold">Indicazioni per l’agente</h2></template>
              <div class="space-y-4"><div v-for="(instruction, title) in engagement.template_revision.instructions" :key="title"><h3 class="font-medium">{{ title }}</h3><p class="whitespace-pre-wrap text-sm text-muted">{{ instruction }}</p></div><p v-if="!Object.keys(engagement.template_revision.instructions).length" class="text-sm text-muted">Nessuna indicazione per questa revisione.</p></div>
            </UCard>
          </aside>
        </div>
        <UCard v-if="reviewing && engagement.pending_migration">
          <template #header><h2 class="text-lg font-semibold">Passa alla revisione {{ engagement.pending_migration.target_revision }}</h2></template>
          <div class="space-y-4">
            <p>Confronta la proposta con il fascicolo salvato. Il testo delle sezioni esistenti viene conservato; le sezioni rimosse restano nel documento e nella cronologia.</p>
            <UAlert v-if="dirty" color="warning" title="Salva prima le modifiche" description="Dopo il salvataggio, riapri il confronto per verificare la proposta aggiornata." />
            <pre class="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-4 text-sm" aria-label="Differenze della migrazione">{{ engagement.pending_migration.diff || 'Nessuna modifica al testo: cambia la revisione del modello o le indicazioni.' }}</pre>
            <details><summary class="cursor-pointer font-medium">Fascicolo proposto completo</summary><pre class="mt-4 max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm">{{ engagement.pending_migration.proposed_markdown }}</pre></details>
          </div>
          <template #footer><UButton :disabled="dirty || saving" :loading="saving" @click="apply">Applica migrazione</UButton></template>
        </UCard>
        <UCard>
          <template #header><h2 class="font-semibold">Cronologia</h2></template>
          <div class="space-y-4"><details v-for="version in engagement.history" :key="version.id"><summary class="cursor-pointer">Versione {{ version.number }} · {{ version.reason.replaceAll('_', ' ') }} · {{ new Date(version.created_at).toLocaleString('it-IT') }}</summary><pre class="mt-4 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-4 text-sm">{{ version.dossier_markdown }}</pre></details></div>
        </UCard>
      </template>
    </div>
  </AppShell>
</template>
