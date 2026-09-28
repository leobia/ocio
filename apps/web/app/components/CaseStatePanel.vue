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
  <aside class="case-panel" aria-labelledby="case-title">
    <div class="case-heading">
      <div><span class="eyebrow">Contesto</span><h2 id="case-title">Dati del caso</h2></div>
      <button class="round-button" aria-label="Aggiungi dato" @click="edit()">+</button>
    </div>
    <p class="case-intro">Dati usati per contestualizzare le risposte. Puoi correggerli in qualsiasi momento.</p>

    <div v-if="!Object.keys(facts).length" class="empty-small">Nessun dato ancora raccolto.</div>
    <div v-for="(fact, key) in facts" :key="key" class="fact-card">
      <div class="fact-top"><strong>{{ key.replaceAll('_', ' ') }}</strong><span :class="['status', fact.status]">{{ fact.status }}</span></div>
      <p>{{ fact.value === null ? 'Da definire' : Array.isArray(fact.value) ? fact.value.join(', ') : fact.value }}</p>
      <div class="fact-bottom">
        <small>{{ fact.source_message_id ? 'Dal dialogo' : 'Correzione manuale' }}</small>
        <button @click="edit(String(key))">Modifica</button>
      </div>
    </div>

    <form v-if="editing !== null" class="fact-form" @submit.prevent="save">
      <h3>{{ editing ? 'Correggi dato' : 'Nuovo dato' }}</h3>
      <label>Nome<input v-model="name" :disabled="Boolean(editing)" maxlength="100"></label>
      <label>Valore<input v-model="value" :disabled="status === 'unknown'"></label>
      <label>Stato
        <select v-model="status">
          <option value="confirmed">Confermato</option>
          <option value="inferred">Dedotto</option>
          <option value="unknown">Sconosciuto</option>
        </select>
      </label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div class="form-actions"><button type="button" @click="editing = null">Annulla</button><button class="small-primary" :disabled="saving">Salva</button></div>
    </form>
  </aside>
</template>
