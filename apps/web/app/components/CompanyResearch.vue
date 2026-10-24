<script setup lang="ts">
import type { Engagement } from '~/types'
const props = defineProps<{ engagement: Engagement, disabled: boolean }>()
const emit = defineEmits<{ changed: [] }>()
interface Proposal { id: string, field: string, value: string, url: string, source_type: string, consulted_at: string, status: string, confirmed_value: string | null }
interface Research { id: string, status: string, message: string, proposals: Proposal[] }
const history = ref<Research[]>([])
const identifier = ref('')
const confirmed = ref(false)
const author = ref('')
const reason = ref('Verifica dei dati pubblicati')
const corrections = ref<Record<string, string>>({})
const busy = ref(false)
const error = ref('')
const base = computed(() => `/api/v1/engagements/${props.engagement.id}/company-research`)
async function load() {
  try { history.value = await $fetch<Research[]>(base.value) }
  catch { error.value = 'Ricerca pubblica non disponibile. Puoi continuare l’incarico.' }
}
onMounted(load)
async function act(path: string, body: Record<string, unknown>) {
  if (!author.value.trim()) { error.value = 'Indica chi conferma i dati.'; return }
  busy.value = true; error.value = ''
  try { await $fetch(`${base.value}${path}`, { method: 'POST', body: { ...body, author: author.value } }); await load(); emit('changed') }
  catch (e: unknown) { error.value = (e as { data?: { detail?: string } }).data?.detail || 'Ricerca non disponibile. Puoi continuare l’incarico.' }
  finally { busy.value = false }
}
</script>

<template>
  <details class="rounded border p-4">
    <summary class="cursor-pointer font-semibold">Dati aziendali pubblici</summary>
    <div class="mt-4 space-y-3">
      <p class="text-sm">Ricerca per {{ engagement.company }} · {{ engagement.site }}. I dati pubblicati non descrivono le condizioni effettive di lavoro.</p>
      <p v-if="error" role="alert" class="text-error">{{ error }}</p>
      <UFormField label="Identificatore impresa (partita IVA o sito ufficiale)"><UInput v-model="identifier" class="w-full" /></UFormField>
      <UFormField label="Operatore che verifica l’impresa"><UInput v-model="author" class="w-full" /></UFormField>
      <UCheckbox v-model="confirmed" label="Confermo l’identità di questa impresa" />
      <UButton :loading="busy" :disabled="disabled || busy || !confirmed || !identifier.trim() || !author.trim()" @click="act('', { company: engagement.company, location: engagement.site, identifier, confirmed })">Cerca dati pubblici</UButton>
      <UFormField label="Motivo della decisione sui dati pubblici"><UInput v-model="reason" class="w-full" /></UFormField>
      <div v-for="search in history" :key="search.id" class="space-y-3 border-t pt-3">
        <p class="text-sm">{{ search.message }} <span v-if="search.status === 'ambigua'">Specifica l’identità e ripeti la ricerca.</span></p>
        <div v-for="p in search.proposals" :key="p.id" class="space-y-2 rounded border p-3 text-sm">
          <strong>{{ p.field.replaceAll('_', ' ') }}</strong><p>{{ p.confirmed_value || p.value }}</p>
          <a :href="p.url" class="break-all underline" target="_blank" rel="noopener noreferrer">{{ p.source_type }}: {{ p.url }}</a>
          <p>{{ new Date(p.consulted_at).toLocaleString('it-IT') }} · {{ p.status.replaceAll('_', ' ') }}</p>
          <template v-if="p.status === 'da_verificare'">
            <UInput v-model="corrections[p.id]" aria-label="Valore corretto" class="w-full" />
            <div class="flex flex-wrap gap-2">
              <UButton size="xs" :disabled="disabled || busy" @click="act(`/${p.id}`, { expected_version: engagement.version, action: 'confermata', reason })">Conferma dato</UButton>
              <UButton size="xs" :disabled="disabled || busy || !corrections[p.id]?.trim()" @click="act(`/${p.id}`, { expected_version: engagement.version, action: 'corretta', value: corrections[p.id], reason })">Correggi dato</UButton>
              <UButton size="xs" color="neutral" :disabled="disabled || busy" @click="act(`/${p.id}`, { expected_version: engagement.version, action: 'rifiutata', reason })">Rifiuta dato</UButton>
            </div>
          </template>
        </div>
      </div>
    </div>
  </details>
</template>
