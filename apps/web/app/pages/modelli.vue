<script setup lang="ts">
import type { DossierTemplate } from '~/types'
import { dossierSections } from '~/utils/dossierSections'
import { parseTemplate, serializeTemplate, type TemplateSection } from '~/utils/templateSections'
useHead({ title: 'Modelli fascicolo — OCIO', htmlAttrs: { lang: 'it' } })
const route = useRoute()
const api = useOcioApi()
const templates = ref<DossierTemplate[]>([])
const selectedId = ref('')
const name = ref('')
const preamble = ref('')
const sections = ref<TemplateSection[]>([])
let nextId = 1
const baseline = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const preview = ref(false)
const selected = computed(() => templates.value.find(item => item.id === selectedId.value))
const revision = computed(() => selected.value?.revisions.at(-1))
const payload = computed(() => serializeTemplate(preamble.value, sections.value))
const snapshot = computed(() => JSON.stringify({ name: name.value, preamble: preamble.value, sections: sections.value.map(({ title, body, instruction }) => ({ title, body, instruction })) }))
const dirty = computed(() => !loading.value && baseline.value !== snapshot.value)
const options = computed(() => templates.value.map(item => ({ label: item.name, value: item.id })))
const backToEngagement = computed(() => typeof route.query.engagement === 'string' ? `/incarichi/${encodeURIComponent(route.query.engagement)}` : '')
const validation = computed(() => {
  if (!name.value.trim()) return 'Inserisci il nome del modello.'
  if (!sections.value.length) return 'Aggiungi almeno una sezione.'
  const titles = sections.value.map(section => section.title.trim())
  if (titles.some(title => !title)) return 'Inserisci un titolo per ogni sezione.'
  if (new Set(titles).size !== titles.length) return 'Ogni sezione deve avere un titolo diverso.'
  if ([preamble.value, ...sections.value.map(section => section.body)].some(text => dossierSections(text).some(section => section.bodyStart > 0))) return 'Per un titolo di secondo livello usa Aggiungi sezione, anziché inserirlo nel contenuto.'
  if (payload.value.markdown.length > 100000) return 'Il modello supera il limite di 100.000 caratteri.'
  return ''
})
useUnsavedChanges(dirty)
function canReplace() { return !dirty.value || window.confirm('Ci sono modifiche non salvate. Vuoi abbandonarle?') }
function edit(template?: DossierTemplate) {
  selectedId.value = template?.id || ''
  name.value = template?.name || ''
  const latest = template?.revisions.at(-1)
  const parsed = parseTemplate(latest?.markdown || '', latest?.instructions || {})
  preamble.value = parsed.preamble
  sections.value = parsed.sections
  nextId = sections.value.length + 1
  if (!template) sections.value.push({ id: nextId++, title: '', body: '', instruction: '' })
  baseline.value = snapshot.value
  error.value = ''
  notice.value = ''
  preview.value = false
}
function select(id: string) {
  if (canReplace()) edit(templates.value.find(item => item.id === id))
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    templates.value = await api.listTemplates()
    edit(templates.value.find(item => item.id === route.query.model) || templates.value[0])
  }
  catch (reason) { error.value = (reason as Error).message }
  finally { loading.value = false }
}
async function addSection() {
  const id = nextId++
  sections.value.push({ id, title: '', body: '', instruction: '' })
  await nextTick()
  document.getElementById(`section-title-${id}`)?.focus()
}
function move(index: number, offset: number) {
  const target = index + offset
  if (target < 0 || target >= sections.value.length) return
  const [section] = sections.value.splice(index, 1)
  if (section) sections.value.splice(target, 0, section)
}
async function save() {
  if (saving.value || validation.value || (selected.value && !dirty.value)) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    if (selected.value) {
      const target = selected.value
      const created = await api.reviseTemplate(target.id, payload.value)
      target.revisions.push(created)
      edit(target)
      notice.value = `Revisione ${created.number} creata. Gli incarichi collegati possono ora valutarne la migrazione.`
    }
    else {
      const created = await api.createTemplate({ name: name.value.trim(), ...payload.value })
      templates.value.push(created)
      edit(created)
      notice.value = 'Modello creato. Puoi usarlo per un nuovo incarico.'
    }
  }
  catch (reason) { error.value = (reason as Error).message }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <AppShell section="Modelli fascicolo">
    <template #actions><UButton v-if="backToEngagement" :to="backToEngagement" color="neutral" variant="outline">Torna al fascicolo</UButton><UButton icon="i-lucide-plus" :disabled="saving || loading" @click="() => { if (canReplace()) edit() }">Nuovo modello</UButton></template>
    <div class="mx-auto max-w-3xl space-y-6 p-4 sm:p-6">
      <UAlert v-if="error" role="alert" color="error" :title="error" :actions="!baseline ? [{ label: 'Riprova', onClick: load }] : []" />
      <p v-if="loading" role="status">Caricamento modelli…</p>
      <p v-if="notice" role="status" class="text-success">{{ notice }}</p>
      <form v-if="!loading && baseline" class="space-y-6" @submit.prevent="save">
        <UFormField v-if="options.length" label="Modello da modificare"><USelect :model-value="selectedId || undefined" :items="options" :disabled="saving" placeholder="Nuovo modello" class="w-full" @update:model-value="select" /></UFormField>
        <fieldset :disabled="saving" class="space-y-6">
          <UFormField label="Nome del modello" required><UInput v-model="name" :disabled="Boolean(selected)" maxlength="200" required class="w-full" /></UFormField>
          <div v-if="revision" class="flex flex-wrap items-center gap-3"><UBadge variant="subtle">Revisione {{ revision.number }}</UBadge><p class="text-sm text-muted">Salvare crea una nuova revisione, senza aggiornare automaticamente gli incarichi.</p></div>
          <div><h2 class="text-lg font-semibold">Sezioni del fascicolo</h2><p class="text-muted">Definisci la struttura del fascicolo e cosa deve contenere ogni sezione.</p></div>
          <details><summary class="cursor-pointer text-sm text-muted">Introduzione del modello (facoltativa)</summary><UFormField class="mt-4" label="Introduzione Markdown"><UTextarea v-model="preamble" :rows="3" class="w-full" /></UFormField></details>
          <UCard v-for="(section, index) in sections" :key="section.id" as="section" :aria-label="`Sezione ${index + 1}`">
            <template #header><div class="flex flex-wrap items-center justify-between gap-3"><h3 class="font-semibold">Sezione {{ index + 1 }}</h3><div class="flex gap-1"><UButton icon="i-lucide-arrow-up" color="neutral" variant="ghost" :disabled="index === 0 || saving" :aria-label="`Sposta su sezione ${index + 1}`" @click="move(index, -1)" /><UButton icon="i-lucide-arrow-down" color="neutral" variant="ghost" :disabled="index === sections.length - 1 || saving" :aria-label="`Sposta giù sezione ${index + 1}`" @click="move(index, 1)" /><UButton icon="i-lucide-trash-2" color="neutral" variant="ghost" :disabled="saving" :aria-label="`Rimuovi sezione ${index + 1}`" @click="sections.splice(index, 1)" /></div></div></template>
            <div class="space-y-4">
              <UFormField label="Titolo della sezione" required><UInput :id="`section-title-${section.id}`" v-model="section.title" required class="w-full" /></UFormField>
              <UFormField label="Descrizione della sezione" description="Contenuti da trattare e approfondimenti specifici di questa sezione."><UTextarea v-model="section.instruction" :rows="3" class="w-full" /></UFormField>
              <details><summary class="cursor-pointer text-sm text-muted">Contenuto iniziale{{ section.body ? ' · presente' : ' (facoltativo)' }}</summary><UFormField class="mt-4" label="Contenuto iniziale Markdown"><UTextarea v-model="section.body" :rows="4" class="w-full" /></UFormField></details>
            </div>
          </UCard>
          <p v-if="!sections.length" class="text-muted">Aggiungi la prima sezione per iniziare.</p>
          <div class="flex flex-wrap justify-between gap-3"><UButton icon="i-lucide-plus" color="neutral" variant="outline" @click="addSection">Aggiungi sezione</UButton><UButton color="neutral" variant="ghost" :aria-expanded="preview" @click="preview = !preview">{{ preview ? 'Nascondi anteprima' : 'Anteprima modello' }}</UButton></div>
          <UCard v-if="preview"><template #header><h2 class="font-semibold">Anteprima modello</h2></template><pre class="whitespace-pre-wrap break-words text-sm">{{ payload.markdown }}</pre><dl class="mt-6 space-y-4"><div v-for="(instruction, title) in payload.instructions" :key="title"><dt class="font-medium">{{ title }}</dt><dd class="whitespace-pre-wrap text-sm text-muted">{{ instruction }}</dd></div></dl></UCard>
          <p v-if="validation" role="status" class="text-sm text-muted">{{ validation }}</p>
          <div class="flex flex-wrap justify-end gap-3"><UButton v-if="selected && !dirty" to="/incarichi/nuovo" color="neutral" variant="outline">Nuovo incarico</UButton><UButton type="submit" :disabled="Boolean(validation) || saving || Boolean(selected && !dirty)" :loading="saving">{{ selected ? 'Crea revisione' : 'Crea modello' }}</UButton></div>
        </fieldset>
      </form>
    </div>
  </AppShell>
</template>
