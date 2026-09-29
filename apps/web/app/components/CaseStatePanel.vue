<script setup lang="ts">
import type { CaseFact } from '~/types'

const props = defineProps<{ conversationId: string, facts: Record<string, CaseFact> }>()
const emit = defineEmits<{ updated: [facts: Record<string, CaseFact>] }>()
const api = useOcioApi()
const editing = ref<string | null>(null)
const name = ref('')
const value = ref('')
const status = ref<CaseFact['status']>('confirmed')
const error = ref('')
const saving = ref(false)

function edit(key = '') {
  const fact = props.facts[key]
  editing.value = key
  name.value = key
  value.value = Array.isArray(fact?.value) ? fact.value.join(', ') : String(fact?.value ?? '')
  status.value = fact?.status || 'confirmed'
  error.value = ''
}

function typedValue(original: CaseFact['value'] | undefined) {
  if (status.value === 'unknown') return null
  if (typeof original === 'number') return Number(value.value)
  if (typeof original === 'boolean') return value.value.toLowerCase() === 'true'
  if (Array.isArray(original)) return value.value.split(',').map(item => item.trim()).filter(Boolean)
  return value.value.trim()
}

async function save() {
  if (!name.value.trim() || (status.value !== 'unknown' && !value.value.trim())) {
    error.value = 'Nome e valore sono obbligatori.'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const result = await api.updateFact(props.conversationId, name.value.trim(), {
      value: typedValue(props.facts[editing.value || '']?.value), status: status.value,
    })
    emit('updated', result.case_state)
    editing.value = null
  }
  catch (reason) {
    error.value = (reason as Error).message
  }
  finally {
    saving.value = false
  }
}
</script>

<template>
  <UCard as="aside" aria-label="Dati del caso">
    <template #header><div class="flex items-center justify-between gap-3"><h2 class="font-semibold">Dati del caso</h2><UButton icon="i-lucide-plus" color="neutral" variant="ghost" aria-label="Aggiungi dato" @click="edit()" /></div></template>
    <div class="space-y-4">
      <p class="text-sm text-muted">Dati usati per contestualizzare le risposte. Puoi correggerli.</p>
      <p v-if="!Object.keys(facts).length" class="text-sm text-muted">Nessun dato ancora raccolto.</p>
      <div v-for="(fact, key) in facts" :key="key" class="space-y-2 border-t border-default pt-4">
        <div class="flex flex-wrap items-center justify-between gap-2"><strong class="break-words">{{ key.replaceAll('_', ' ') }}</strong><UBadge :color="fact.status === 'confirmed' ? 'success' : fact.status === 'inferred' ? 'warning' : 'neutral'" variant="subtle">{{ fact.status }}</UBadge></div>
        <p class="break-words">{{ fact.value === null ? 'Da definire' : Array.isArray(fact.value) ? fact.value.join(', ') : fact.value }}</p>
        <div class="flex flex-wrap items-center justify-between gap-2"><small class="text-muted">{{ fact.source_message_id ? 'Dal dialogo' : 'Correzione manuale' }}</small><UButton variant="link" @click="edit(String(key))">Modifica</UButton></div>
      </div>
      <form v-if="editing !== null" class="space-y-4 border-t border-default pt-4" @submit.prevent="save">
        <h3 class="font-semibold">{{ editing ? 'Correggi dato' : 'Nuovo dato' }}</h3>
        <UFormField label="Nome"><UInput v-model="name" :disabled="Boolean(editing)" maxlength="100" class="w-full" /></UFormField>
        <UFormField label="Valore"><UInput v-model="value" :disabled="status === 'unknown'" class="w-full" /></UFormField>
        <UFormField label="Stato"><USelect v-model="status" :items="[{ label: 'Confermato', value: 'confirmed' }, { label: 'Dedotto', value: 'inferred' }, { label: 'Sconosciuto', value: 'unknown' }]" class="w-full" /></UFormField>
        <p v-if="error" class="text-sm text-error" role="alert">{{ error }}</p>
        <div class="flex justify-end gap-2"><UButton color="neutral" variant="outline" @click="editing = null">Annulla</UButton><UButton type="submit" :loading="saving">Salva</UButton></div>
      </form>
    </div>
  </UCard>
</template>
