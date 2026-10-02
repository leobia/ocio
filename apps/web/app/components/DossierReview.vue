<script setup lang="ts">
import type { Engagement } from '~/types'
const props = defineProps<{ engagement: Engagement, section: string, body: string, disabled: boolean }>()
const emit = defineEmits<{ changed: [] }>()
interface Proposal { id: string, section: string, previous: string, proposed: string, status: string, references: string[] }
interface Review { proposals: Proposal[], approvals: { id: string, author: string, created_at: string }[], sources: { id: string, text: string, url: string | null }[] }
const review = ref<Review>({ proposals: [], approvals: [], sources: [] })
const author = ref('')
const reason = ref('')
const correction = ref('')
const error = ref('')
const busy = ref(false)
const proposals = computed(() => review.value.proposals.filter(p => p.section === props.section && ['proposta', 'bozza'].includes(p.status)))
const sources = computed(() => review.value.sources.filter(s => props.body.includes(s.id) || proposals.value.some(p => p.references.includes(s.id))))
const base = computed(() => `/api/v1/engagements/${props.engagement.id}`)
watch(() => props.engagement.version, async () => {
  try { review.value = await $fetch<Review>(`${base.value}/review`) }
  catch { error.value = 'Impossibile caricare la revisione.' }
}, { immediate: true })
watch(() => props.section, () => { correction.value = '' })
async function act(path: string, extra: Record<string, unknown> = {}) {
  if (!author.value.trim() || !reason.value.trim()) { error.value = 'Indica autore e motivazione della revisione.'; return }
  busy.value = true
  error.value = ''
  try {
    await $fetch(`${base.value}${path}`, { method: 'POST', body: { expected_version: props.engagement.version, author: author.value, reason: reason.value, ...extra } })
    emit('changed')
  }
  catch (e: unknown) { error.value = (e as { data?: { detail?: string } }).data?.detail || 'Revisione non salvata. Ricarica e riprova.' }
  finally { busy.value = false }
}
</script>

<template>
  <UCard class="mt-4">
    <template #header><h3 class="font-semibold">Revisione e approvazione</h3></template>
    <div class="space-y-3">
      <p v-if="error" role="alert" class="text-error">{{ error }}</p>
      <p class="text-sm">Le modifiche manuali e il testo approvato sono protetti. Le proposte successive richiedono una decisione.</p>
      <UFormField label="Autore della revisione"><UInput v-model="author" class="w-full" /></UFormField>
      <UFormField label="Motivazione della revisione"><UInput v-model="reason" class="w-full" /></UFormField>
      <div v-for="p in proposals" :key="p.id" class="space-y-3 rounded border p-3">
        <strong>{{ p.status === 'bozza' ? 'Bozza dell’agente da revisionare' : 'Proposta sul testo protetto' }}</strong>
        <details><summary>Testo precedente</summary><pre class="whitespace-pre-wrap text-sm">{{ p.previous }}</pre></details>
        <p class="text-sm font-medium">Testo proposto</p><pre class="whitespace-pre-wrap text-sm">{{ p.proposed }}</pre>
        <div class="flex flex-wrap gap-2">
          <UButton :disabled="disabled || busy" @click="act(`/review/${p.id}`, { action: 'accettata' })">Accetta sezione</UButton>
          <UButton color="neutral" :disabled="disabled || busy" @click="correction = p.proposed">Prepara correzione</UButton>
          <UButton color="error" variant="outline" :disabled="disabled || busy" @click="act(`/review/${p.id}`, { action: 'rifiutata' })">Rifiuta proposta</UButton>
        </div>
        <template v-if="correction"><UFormField label="Testo corretto"><UTextarea v-model="correction" :rows="8" class="w-full" /></UFormField><UButton :disabled="disabled || busy" @click="act(`/review/${p.id}`, { action: 'corretta', body: correction })">Salva correzione</UButton></template>
      </div>
      <details v-if="sources.length"><summary>Fonti del contenuto</summary><div v-for="s in sources" :key="s.id" class="my-3 text-sm"><p class="break-all text-xs">{{ s.id }}</p><p class="whitespace-pre-wrap">{{ s.text }}</p><a v-if="s.url" :href="s.url" class="underline" target="_blank" rel="noopener noreferrer">Apri fonte</a></div></details>
      <details><summary>Anteprima complessiva da approvare</summary><pre class="max-h-96 overflow-auto whitespace-pre-wrap text-sm">{{ engagement.exportable_markdown }}</pre><p v-for="(decision, title) in engagement.relevance" :key="title" class="text-sm">{{ title }}: {{ decision.status.replaceAll('_', ' ') }} — {{ decision.reason }}</p></details>
      <UButton :disabled="disabled || busy" @click="act('/approvals')">Approva revisione complessiva</UButton>
      <p class="text-xs text-muted">L’approvazione conserva anche i punti da chiarire e non costituisce una dichiarazione di conformità.</p>
      <div v-for="approval in review.approvals" :key="approval.id" class="text-sm"><a :href="`${base}/approvals/${approval.id}/export`" class="underline">Esporta Markdown approvato</a> · {{ approval.author }} · {{ new Date(approval.created_at).toLocaleString('it-IT') }}</div>
      <details><summary>Ripristina una versione precedente</summary><div v-for="version in engagement.history" :key="version.id" class="my-2 flex items-center gap-2 text-sm"><span>Versione {{ version.number }}</span><UButton size="xs" color="neutral" :disabled="disabled || busy" @click="act(`/restore/${version.id}`)">Ripristina</UButton></div></details>
    </div>
  </UCard>
</template>
