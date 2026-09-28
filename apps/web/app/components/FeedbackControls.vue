<script setup lang="ts">
const props = defineProps<{ messageId: string }>()
const api = useOcioApi()
const rating = ref<number>()
const expanded = ref(false)
const reason = ref('')
const details = ref('')
const state = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')

async function save(values: { rating?: number, reason?: string, details?: string }) {
  state.value = 'saving'
  try {
    await api.sendFeedback(props.messageId, values)
    state.value = 'saved'
  }
  catch {
    state.value = 'error'
  }
}

function rate(value: number) {
  rating.value = value
  void save({ rating: value })
}

function saveDetails() {
  const values: { reason?: string, details?: string } = {}
  if (reason.value) values.reason = reason.value
  if (details.value.trim()) values.details = details.value.trim()
  if (Object.keys(values).length) void save(values)
}
</script>

<template>
  <div class="feedback" aria-label="Feedback sulla risposta">
    <span class="feedback-label">È stata utile?</span>
    <button class="icon-button" :class="{ selected: rating === 5 }" aria-label="Risposta utile" @click="rate(5)">↑</button>
    <button class="icon-button" :class="{ selected: rating === 1 }" aria-label="Risposta non utile" @click="rate(1)">↓</button>
    <button class="detail-button" :aria-expanded="expanded" @click="expanded = !expanded">Aggiungi dettagli</button>
    <span class="save-state" aria-live="polite">{{ state === 'saved' ? 'Salvato' : state === 'error' ? 'Errore' : '' }}</span>
    <form v-if="expanded" class="feedback-detail" @submit.prevent="saveDetails">
      <label>Motivo
        <select v-model="reason">
          <option value="">Seleziona</option>
          <option value="answer">Risposta</option>
          <option value="citation">Fonte</option>
          <option value="incomplete">Incompleta</option>
        </select>
      </label>
      <label>Nota opzionale
        <textarea v-model="details" rows="2" maxlength="2000" />
      </label>
      <button class="small-primary" type="submit" :disabled="state === 'saving'">Salva dettagli</button>
    </form>
  </div>
</template>
