<script setup lang="ts">
import type { DossierAgentRun, Engagement, EngagementMessage } from '~/types'
import { dossierSections, replaceSection } from '~/utils/dossierSections'
definePageMeta({ key: route => String(route.params.id) })
const api = useOcioApi()
const route = useRoute()
const engagement = ref<Engagement | null>(null)
const evidenceMessages = ref<EngagementMessage[]>([])
const agentRun = ref<DossierAgentRun | null>(null)
const runningAgent = ref(false)
const relevanceReason = ref('')
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
async function refresh() {
  if (engagement.value) accept(await api.getEngagement(engagement.value.id))
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const id = String(route.params.id)
    const [result, messages, run] = await Promise.all([api.getEngagement(id), api.getEngagementMessages(id), api.getEngagementAgent(id)])
    accept(result)
    evidenceMessages.value = messages
    agentRun.value = run
  }
  catch (reason) { error.value = (reason as Error).message }
  finally { loading.value = false }
}
function onEvidenceSent(message: EngagementMessage) {
  evidenceMessages.value = [...evidenceMessages.value, message]
  if (agentRun.value?.status === 'in_attesa') void runAgent()
}
async function runAgent() {
  if (!engagement.value || dirty.value || runningAgent.value) return
  runningAgent.value = true
  error.value = ''
  notice.value = ''
  const id = engagement.value.id
  const poll = setInterval(async () => {
    try {
      const [run, current] = await Promise.all([api.getEngagementAgent(id), api.getEngagement(id)])
      agentRun.value = run
      if (current.version !== engagement.value?.version && !dirty.value) accept(current)
    }
    catch { /* The initiating request reports errors. */ }
  }, 2000)
  try {
    agentRun.value = await api.startEngagementAgent(id)
    const [result, messages] = await Promise.all([api.getEngagement(id), api.getEngagementMessages(id)])
    accept(result)
    evidenceMessages.value = messages
    notice.value = agentRun.value.status === 'fallito' ? 'Compilazione interrotta: consulta la trace.' : 'Bozza aggiornata.'
  }
  catch (reason) { error.value = (reason as Error).message }
  finally { clearInterval(poll); runningAgent.value = false }
}
async function setRelevance(status: Engagement['relevance'][string]['status']) {
  if (!engagement.value || dirty.value) return
  const reason = relevanceReason.value.trim() || 'Decisione corretta dall’RSPP.'
  try {
    accept(await api.setEngagementRelevance(engagement.value.id, section.value.title, { status, reason, references: [] }))
    relevanceReason.value = ''
    if (agentRun.value?.status === 'in_attesa') void runAgent()
  }
  catch (problem) { error.value = (problem as Error).message }
}
async function linkEvidence(observationId: string, target: string | null) {
  if (!engagement.value) return
  error.value = ''
  try {
    await api.linkObservation(engagement.value.id, observationId, target)
    for (const message of evidenceMessages.value) {
      const item = message.observations.find(observation => observation.id === observationId)
      if (item) item.section = target
    }
  }
  catch (reason) { error.value = (reason as Error).message }
}
const linkedEvidence = computed(() => evidenceMessages.value.flatMap(message => message.observations.filter(item => item.section === section.value.title).map(item => ({ ...item, message }))))
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
    if (agentRun.value?.status === 'in_attesa') void runAgent()
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
    <template #actions><UButton v-if="engagement" :loading="saving" :disabled="!dirty || saving || runningAgent" @click="save">Salva fascicolo</UButton></template>
    <div class="space-y-6 p-4 sm:p-6">
      <UAlert v-if="error" role="alert" color="error" :title="error" :actions="!engagement ? [{ label: 'Riprova', onClick: load }] : []" />
      <p v-if="loading" role="status">Caricamento fascicolo…</p>
      <p v-if="notice" role="status" class="text-success">{{ notice }}</p>
      <template v-if="engagement && !loading">
        <header class="flex flex-wrap items-center justify-between gap-4">
          <div><h2 class="text-2xl font-semibold">{{ engagement.company }}</h2><p class="mt-1 text-sm text-muted">{{ engagement.site }} · {{ engagement.template.name }} · revisione {{ engagement.template_revision.number }}</p></div>
          <UButton color="neutral" variant="outline" :aria-expanded="showDetails" @click="showDetails = !showDetails">{{ showDetails ? 'Chiudi dettagli' : 'Dettagli incarico' }}</UButton>
        </header>
        <div class="engagement-layout">
          <div class="min-w-0 space-y-4">
            <UCard>
              <template #header><h3 class="font-semibold">Compilazione assistita</h3></template>
              <p class="text-sm">Stato: {{ (agentRun?.status || engagement.status).replaceAll('_', ' ') }}</p>
              <p v-if="agentRun?.plan" class="mt-2 whitespace-pre-wrap text-sm text-muted">{{ agentRun.plan }}</p>
              <p v-if="runningAgent" role="status" class="mt-2 text-sm">OCIO sta aggiornando il fascicolo… {{ agentRun?.events.length || 0 }} eventi registrati</p>
              <p v-if="agentRun?.status === 'fallito'" role="alert" class="mt-2 text-sm text-error">{{ agentRun.reason }}</p>
              <template #footer><UButton :loading="runningAgent" :disabled="runningAgent || dirty || saving" @click="runAgent">{{ agentRun ? 'Continua compilazione' : 'Avvia compilazione' }}</UButton></template>
            </UCard>
            <CompanyResearch :engagement="engagement" :disabled="dirty || saving || runningAgent" @changed="refresh" />
            <EngagementEvidence :engagement-id="engagement.id" :messages="evidenceMessages" :sections="sections.filter(item => item.title !== 'Introduzione').map(item => item.title)" @sent="onEvidenceSent" @link="linkEvidence" />
          </div>
          <div class="min-w-0 space-y-5">
        <UAlert v-if="engagement.pending_migration" color="warning" variant="subtle" :title="`Revisione ${engagement.pending_migration.target_revision} disponibile`" description="Il fascicolo resta sulla revisione corrente finché non applichi la proposta.">
          <template #actions><UButton color="warning" variant="outline" :disabled="saving" @click="reviewing = !reviewing">{{ reviewing ? 'Chiudi confronto' : 'Confronta proposta' }}</UButton></template>
        </UAlert>
        <div class="dossier-layout" :class="{ 'with-details': showDetails }">
          <nav class="section-index" aria-label="Sezioni del fascicolo">
            <h3 class="mb-3 px-3 text-sm font-semibold">Sezioni</h3>
            <button v-for="(item, index) in sections" :key="index" :aria-current="activeSection === index ? 'page' : undefined" :disabled="saving" @click="activeSection = index; sourceMode = false"><span class="text-xs text-muted">{{ String(index + 1).padStart(2, '0') }}</span><span>{{ item.title }}</span></button>
          </nav>
          <section class="min-w-0" :aria-label="section.title">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted"><span role="status">{{ dirty ? 'Modifiche non salvate' : 'Tutte le modifiche sono salvate' }}</span><UButton color="neutral" variant="link" size="xs" :disabled="saving || runningAgent" @click="sourceMode = !sourceMode; editorVersion++">{{ sourceMode ? 'Torna alle sezioni' : 'Modifica Markdown' }}</UButton></div>
            <div v-if="section.title !== 'Introduzione'" class="mb-3 rounded-lg border p-3 text-sm">
              <label :for="`relevance-${activeSection}`">Pertinenza della sezione</label>
              <select :id="`relevance-${activeSection}`" class="ml-2 rounded border bg-default p-1" :value="engagement.relevance[section.title]?.status || 'da_valutare'" :disabled="dirty || runningAgent" @change="setRelevance(($event.target as HTMLSelectElement).value as Engagement['relevance'][string]['status'])"><option value="da_valutare">Da valutare</option><option value="pertinente">Pertinente</option><option value="non_pertinente">Non pertinente</option><option value="da_chiarire">Da chiarire</option></select>
              <p v-if="engagement.relevance[section.title]" class="mt-1 text-muted">{{ engagement.relevance[section.title]?.reason }}</p>
              <input v-model="relevanceReason" class="mt-2 w-full rounded border bg-default p-1" placeholder="Motivo della correzione" :disabled="dirty || runningAgent">
            </div>
            <div class="document-paper">
              <template v-if="!sourceMode">
                <h3 class="mb-8 font-serif text-2xl">{{ section.title }}</h3>
                <DossierSectionEditor :key="`${editorVersion}-${activeSection}`" v-model="sectionBody" :title="section.title" :disabled="saving || runningAgent" />
              </template>
              <UFormField v-else label="Fascicolo Markdown"><UTextarea v-model="markdown" :rows="26" :disabled="saving || runningAgent" class="w-full font-mono" /></UFormField>
            </div>
            <QualitySignal :engagement="engagement" :section="section.title" :disabled="dirty || saving || runningAgent" />
            <DossierReview :engagement="engagement" :section="section.title" :body="sectionBody" :disabled="dirty || runningAgent || saving" @changed="refresh" />
            <UCard v-if="linkedEvidence.length" class="mt-4">
              <template #header><h3 class="font-semibold">Evidenze collegate a questa sezione</h3></template>
              <div class="space-y-3 text-sm"><div v-for="item in linkedEvidence" :key="item.id" class="border-b pb-2"><strong>{{ item.information }}</strong><p class="whitespace-pre-wrap">{{ item.text }}</p><p class="text-xs text-muted">{{ item.status.replaceAll('_', ' ') }} · {{ item.position || 'Appunto' }} · {{ item.method }}</p><a v-if="item.attachment_id" class="underline" :href="api.attachmentUrl(engagement.id, item.attachment_id)">Apri originale</a><span v-else class="text-muted">Messaggio nella chat</span></div></div>
            </UCard>
            <UCard v-if="engagement.proposed_facts.some(item => item.section === section.title)" class="mt-4">
              <template #header><h3 class="font-semibold">Fatti proposti</h3></template>
              <div v-for="item in engagement.proposed_facts.filter(item => item.section === section.title)" :key="item.id" class="mb-2 text-sm"><p>{{ item.text }}</p><p class="text-xs text-muted">Fonti: {{ item.references.join(', ') }}</p></div>
            </UCard>
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
              <p v-if="engagement.template_revision.relevance_guidance[section.title]" class="mt-3 whitespace-pre-wrap text-sm text-muted">Pertinenza: {{ engagement.template_revision.relevance_guidance[section.title] }}</p>
            </UCard>
            <UCard v-if="engagement.relevance_history.some(item => item.section === section.title)">
              <template #header><h3 class="font-semibold">Decisioni di pertinenza</h3></template>
              <div v-for="item in engagement.relevance_history.filter(item => item.section === section.title)" :key="item.id" class="mb-3 text-sm"><strong>{{ item.status.replaceAll('_', ' ') }}</strong> · {{ item.origin }}<p>{{ item.reason }}</p></div>
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
        <details class="rounded-lg border p-4"><summary class="cursor-pointer font-semibold">Bozza esportabile</summary><pre class="mt-3 max-h-96 overflow-auto whitespace-pre-wrap text-sm">{{ engagement.exportable_markdown }}</pre></details>
          </div>
        </div>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.engagement-layout{display:grid;grid-template-columns:minmax(300px, .8fr) minmax(0, 1.5fr);gap:24px;align-items:start}
.dossier-layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:28px;align-items:start}.dossier-layout.with-details{grid-template-columns:190px minmax(0,1fr) 280px;gap:20px}
.section-index{position:sticky;top:20px}.section-index button{display:flex;gap:12px;text-align:left;width:100%;padding:12px;border-radius:6px;font-size:13px;line-height:1.5;cursor:pointer}.section-index button[aria-current=page]{background:var(--ui-bg-elevated);color:var(--ui-primary);font-weight:600}.section-index button:disabled{opacity:.6;cursor:default}.document-paper{border:1px solid var(--ui-border);background:var(--ui-bg);padding:40px;min-height:650px;max-width:960px;margin:auto}
@media(max-width:1200px){.dossier-layout.with-details{grid-template-columns:180px minmax(0,1fr)}.dossier-layout aside{grid-column:2}}
@media(max-width:1100px){.engagement-layout{grid-template-columns:1fr}}
@media(max-width:700px){.dossier-layout,.dossier-layout.with-details{display:flex;flex-direction:column;gap:20px}.dossier-layout>section,.dossier-layout>aside{width:100%}.section-index{position:static;display:flex;overflow:auto;width:100%;gap:6px;padding-bottom:8px}.section-index h3{display:none}.section-index button{min-width:150px}.document-paper{padding:22px;min-height:550px}}
</style>
