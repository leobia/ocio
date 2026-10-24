<script setup lang="ts">
interface Candidate { id: string, engagement_id: string, run_id: string | null, revision_id: string, section: string | null, category: string, detail: string, author: string, cause: string | null, status: string, created_at: string }
interface Audit { author: string, reason: string, scope: string, cause: string, versions: Record<string, unknown>, created_at: string }
const candidates = ref<Candidate[]>([])
const selected = ref<Candidate | null>(null)
const audit = ref<Audit[]>([])
const author = ref('')
const reason = ref('')
const cause = ref('dato_del_caso')
const action = ref('scartato')
const body = ref('')
const reviewedVersion = ref<number | null>(null)
const section = ref('Attività')
const notes = ref('')
const reference = ref('')
const description = ref('Descrivere solo le attività documentate.')
const expectedRelevance = ref('pertinente')
const required = ref('')
const forbidden = ref('')
const anonymized = ref(false)
const error = ref('')
const busy = ref(false)
useHead({ title: 'Qualità — OCIO' })
async function load() {
  try { candidates.value = await $fetch<Candidate[]>('/api/v1/quality') }
  catch { error.value = 'Inbox qualità non disponibile.' }
}
async function select(item: Candidate) {
  selected.value = item; reason.value = ''; body.value = ''; notes.value = ''; reference.value = ''; anonymized.value = false
  cause.value = item.cause || 'dato_del_caso'
  action.value = item.status === 'aperto' ? 'scartato' : 'aperto'
  reviewedVersion.value = null
  try {
    const [events, engagement] = await Promise.all([$fetch<Audit[]>(`/api/v1/quality/${item.id}/history`), $fetch<{ version: number }>(`/api/v1/engagements/${item.engagement_id}`)])
    audit.value = events; reviewedVersion.value = engagement.version
  }
  catch { error.value = 'Cronologia non disponibile.' }
}
async function save() {
  if (!selected.value) return
  busy.value = true; error.value = ''
  try {
    const payload: Record<string, unknown> = { cause: cause.value, action: action.value, author: author.value, reason: reason.value }
    if (action.value === 'solo_incarico') {
      payload.expected_version = reviewedVersion.value
      payload.body = body.value
    }
    if (action.value === 'regressione') {
      payload.anonymized_confirmed = anonymized.value
      payload.regression_case = { company: 'Impresa fittizia regressione', template: `# Fascicolo fittizio\n\n## ${section.value}\n`, descriptions: { [section.value]: description.value }, notes: notes.value, expected_relevance: { [section.value]: expectedRelevance.value }, required_terms: required.value.split('\n').filter(Boolean), forbidden_terms: forbidden.value.split('\n').filter(Boolean), reference: reference.value }
    }
    await $fetch(`/api/v1/quality/${selected.value.id}`, { method: 'POST', body: payload })
    await load()
    const updated = candidates.value.find(c => c.id === selected.value?.id)
    if (updated) await select(updated)
  }
  catch (e: unknown) { error.value = (e as { data?: { detail?: string } }).data?.detail || 'Decisione non salvata. Verifica i campi e riprova.' }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <AppShell section="Qualità">
    <div class="space-y-5 p-4 sm:p-6">
      <h2 class="text-2xl font-semibold">Inbox qualità</h2>
      <p>Il responsabile valuta le segnalazioni. Nessuna decisione modifica automaticamente istruzioni, memoria condivisa o fonti normative.</p>
      <p v-if="error" role="alert" class="text-error">{{ error }}</p>
      <div class="grid gap-6 lg:grid-cols-2">
        <div class="space-y-3"><p v-if="!candidates.length">Nessun candidato.</p><button v-for="item in candidates" :key="item.id" class="block w-full rounded border p-4 text-left" @click="select(item)"><strong>{{ item.category.replaceAll('_', ' ') }}</strong> · {{ item.status.replaceAll('_', ' ') }}<p>{{ item.detail }}</p><p class="text-sm text-muted">{{ item.section || 'Intero incarico' }} · {{ new Date(item.created_at).toLocaleString('it-IT') }}</p></button></div>
        <UCard v-if="selected">
          <template #header><h3 class="font-semibold">Valuta il candidato</h3></template>
          <div class="space-y-3">
            <NuxtLink :to="`/incarichi/${selected.engagement_id}`" class="underline">Apri incarico ed evidenze</NuxtLink>
            <p class="break-all text-xs text-muted">Run: {{ selected.run_id || 'Nessuno' }} · Revisione: {{ selected.revision_id }}</p>
            <UFormField label="Responsabile della decisione"><UInput v-model="author" class="w-full" /></UFormField>
            <label class="block">Causa <select v-model="cause" class="rounded border bg-default p-1"><option value="dato_del_caso">Dato del caso</option><option value="estrazione">Estrazione</option><option value="ricerca_normativa">Ricerca normativa</option><option value="scelta_tool">Scelta del tool</option><option value="istruzione">Istruzione</option><option value="output_finale">Output finale</option></select></label>
            <label class="block">Decisione <select v-model="action" class="rounded border bg-default p-1"><template v-if="selected.status === 'aperto'"><option value="scartato">Scarta</option><option value="solo_incarico">Correggi solo l’incarico</option><option value="regressione">Promuovi caso anonimizzato</option></template><option v-else value="aperto">Riapri e revoca la promozione</option></select></label>
            <UFormField label="Motivazione della decisione"><UTextarea v-model="reason" class="w-full" /></UFormField>
            <template v-if="action === 'solo_incarico'"><p class="text-sm">Correzione di {{ selected.section || 'nessuna sezione selezionata' }}. Verifica il contenuto nell’incarico prima di salvarlo.</p><UFormField label="Testo corretto della sezione"><UTextarea v-model="body" :rows="8" class="w-full" /></UFormField><p class="text-sm">Nuove fonti normative richiedono acquisizione e verifica nel corpus autorevole.</p></template>
            <template v-if="action === 'regressione'">
              <p class="text-sm">Riscrivi il problema con dati interamente fittizi. Non copiare allegati, nomi, contatti o identificatori del caso originale.</p>
              <UFormField label="Sezione del caso fittizio"><UInput v-model="section" /></UFormField>
              <UFormField label="Indicazioni del modello fittizio"><UTextarea v-model="description" class="w-full" /></UFormField>
              <UFormField label="Appunti anonimizzati"><UTextarea v-model="notes" :rows="5" class="w-full" /></UFormField>
              <label class="block">Pertinenza attesa <select v-model="expectedRelevance" class="rounded border bg-default p-1"><option value="pertinente">Pertinente</option><option value="non_pertinente">Non pertinente</option><option value="da_chiarire">Da chiarire</option></select></label>
              <UFormField label="Sezione professionale di riferimento"><UTextarea v-model="reference" :rows="5" class="w-full" /></UFormField>
              <UFormField label="Dettagli attesi, uno per riga"><UTextarea v-model="required" class="w-full" /></UFormField>
              <UFormField label="Affermazioni da escludere, una per riga"><UTextarea v-model="forbidden" class="w-full" /></UFormField>
              <UCheckbox v-model="anonymized" label="Ho verificato anonimizzazione e riferimento professionale" />
            </template>
            <UButton :disabled="busy || !author.trim() || !reason.trim()" :loading="busy" @click="save">Salva decisione</UButton>
            <details><summary>Cronologia delle decisioni</summary><div v-for="(event, index) in audit" :key="index" class="my-3 text-sm"><strong>{{ event.author }} · {{ event.scope.replaceAll('_', ' ') }}</strong><p>{{ event.reason }}</p><p>{{ new Date(event.created_at).toLocaleString('it-IT') }}</p></div></details>
          </div>
        </UCard>
      </div>
    </div>
  </AppShell>
</template>
