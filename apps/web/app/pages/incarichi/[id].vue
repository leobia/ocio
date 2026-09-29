<script setup lang="ts">
import type { Engagement } from '~/types'
import { dossierSections, replaceSection } from '~/utils/dossierSections'
definePageMeta({ key: route => String(route.params.id) })
const api = useOcioApi()
const route = useRoute()
const engagement = ref<Engagement | null>(null)
const markdown = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const reviewing = ref(false)
const activeSection = ref(0)
const showDetails = ref(false)
const sourceMode = ref(false)
const editorVersion = ref(0)
const sections = computed(() => dossierSections(markdown.value))
const section = computed(() => sections.value[Math.min(activeSection.value, sections.value.length - 1)]!)
const sectionBody = computed({
  get: () => markdown.value.slice(section.value.bodyStart, section.value.end),
  set: value => { markdown.value = replaceSection(markdown.value, activeSection.value, value) },
})
watch(sections, items => { if (activeSection.value >= items.length) activeSection.value = items.length - 1 })
const dirty = computed(() => engagement.value !== null && markdown.value !== engagement.value.dossier_markdown)
useUnsavedChanges(dirty)
useHead({ title: computed(() => `${engagement.value?.company || 'Fascicolo'} — OCIO`), htmlAttrs: { lang: 'it' } })
function accept(result: Engagement) {
  const title = engagement.value ? section.value.title : ''
  engagement.value = result
  markdown.value = result.dossier_markdown
  const previous = sections.value.findIndex(item => item.title === title)
  activeSection.value = previous >= 0 ? previous : sections.value.length > 1 && sections.value[0]?.title === 'Introduzione' ? 1 : 0
  editorVersion.value++
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
onMounted(load)
</script>

<template>
  <AppShell section="Fascicolo" back>
    <template #actions><UButton v-if="engagement" :loading="saving" :disabled="!dirty || saving" @click="save">Salva fascicolo</UButton></template>
    <div class="space-y-6 p-4 sm:p-6">
      <UAlert v-if="error" role="alert" color="error" :title="error" :actions="!engagement ? [{ label: 'Riprova', onClick: load }] : []" />
      <p v-if="loading" role="status">Caricamento fascicolo…</p>
      <p v-if="notice" role="status" class="text-success">{{ notice }}</p>
      <template v-if="engagement && !loading">
        <header class="flex flex-wrap items-center justify-between gap-4">
          <div><h2 class="text-2xl font-semibold">{{ engagement.company }}</h2><p class="mt-1 text-sm text-muted">{{ engagement.site }} · {{ engagement.template.name }} · revisione {{ engagement.template_revision.number }}</p></div>
          <UButton color="neutral" variant="outline" :aria-expanded="showDetails" @click="showDetails = !showDetails">{{ showDetails ? 'Chiudi dettagli' : 'Dettagli incarico' }}</UButton>
        </header>
        <UAlert v-if="engagement.pending_migration" color="warning" variant="subtle" :title="`Revisione ${engagement.pending_migration.target_revision} disponibile`" description="Il fascicolo resta sulla revisione corrente finché non applichi la proposta.">
          <template #actions><UButton color="warning" variant="outline" :disabled="saving" @click="reviewing = !reviewing">{{ reviewing ? 'Chiudi confronto' : 'Confronta proposta' }}</UButton></template>
        </UAlert>
        <div class="dossier-layout" :class="{ 'with-details': showDetails }">
          <nav class="section-index" aria-label="Sezioni del fascicolo">
            <h3 class="mb-3 px-3 text-sm font-semibold">Sezioni</h3>
            <button v-for="(item, index) in sections" :key="index" :aria-current="activeSection === index ? 'page' : undefined" :disabled="saving" @click="activeSection = index; sourceMode = false"><span class="text-xs text-muted">{{ String(index + 1).padStart(2, '0') }}</span><span>{{ item.title }}</span></button>
          </nav>
          <section class="min-w-0" :aria-label="section.title">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted"><span role="status">{{ dirty ? 'Modifiche non salvate' : 'Tutte le modifiche sono salvate' }}</span><UButton color="neutral" variant="link" size="xs" :disabled="saving" @click="sourceMode = !sourceMode; editorVersion++">{{ sourceMode ? 'Torna alle sezioni' : 'Modifica Markdown' }}</UButton></div>
            <div class="document-paper">
              <template v-if="!sourceMode">
                <h3 class="mb-8 font-serif text-2xl">{{ section.title }}</h3>
                <DossierSectionEditor :key="`${editorVersion}-${activeSection}`" v-model="sectionBody" :title="section.title" :disabled="saving" />
              </template>
              <UFormField v-else label="Fascicolo Markdown"><UTextarea v-model="markdown" :rows="26" :disabled="saving" class="w-full font-mono" /></UFormField>
            </div>
          </section>
          <aside v-if="showDetails" class="min-w-0 space-y-5">
            <UCard>
              <template #header><h3 class="font-semibold">Incarico</h3></template>
              <dl class="space-y-4 text-sm"><div><dt class="text-muted">Modello</dt><dd>{{ engagement.template.name }} · revisione {{ engagement.template_revision.number }}</dd></div><div><dt class="text-muted">Riferimento</dt><dd>{{ engagement.reference_date }}</dd></div><div><dt class="text-muted">Ultima modifica</dt><dd>{{ new Date(engagement.updated_at).toLocaleString('it-IT') }}</dd></div></dl>
              <template #footer><UButton variant="link" :to="`/modelli?model=${engagement.template.id}&engagement=${engagement.id}`">Modelli fascicolo</UButton></template>
            </UCard>
            <UCard>
              <template #header><h3 class="font-semibold">Descrizione della sezione</h3></template>
              <p class="mb-2 text-sm font-medium">{{ section.title }}</p><p class="whitespace-pre-wrap text-sm text-muted">{{ engagement.template_revision.instructions[section.title] || 'Nessuna descrizione per questa sezione.' }}</p>
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

<style scoped>
.dossier-layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:28px;align-items:start}.dossier-layout.with-details{grid-template-columns:190px minmax(0,1fr) 280px;gap:20px}
.section-index{position:sticky;top:20px}.section-index button{display:flex;gap:12px;text-align:left;width:100%;padding:12px;border-radius:6px;font-size:13px;line-height:1.5;cursor:pointer}.section-index button[aria-current=page]{background:var(--ui-bg-elevated);color:var(--ui-primary);font-weight:600}.section-index button:disabled{opacity:.6;cursor:default}.document-paper{border:1px solid var(--ui-border);background:var(--ui-bg);padding:40px;min-height:650px;max-width:960px;margin:auto}
@media(max-width:1200px){.dossier-layout.with-details{grid-template-columns:180px minmax(0,1fr)}.dossier-layout aside{grid-column:2}}
@media(max-width:700px){.dossier-layout,.dossier-layout.with-details{display:flex;flex-direction:column;gap:20px}.dossier-layout>section,.dossier-layout>aside{width:100%}.section-index{position:static;display:flex;overflow:auto;width:100%;gap:6px;padding-bottom:8px}.section-index h3{display:none}.section-index button{min-width:150px}.document-paper{padding:22px;min-height:550px}}
</style>
