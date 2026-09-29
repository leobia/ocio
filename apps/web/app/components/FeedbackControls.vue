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
  <div class="flex flex-wrap items-center gap-2 border-t border-default pt-4" aria-label="Feedback sulla risposta">
    <span class="text-sm text-muted">È stata utile?</span>
    <UButton color="neutral" :variant="rating === 5 ? 'soft' : 'ghost'" icon="i-lucide-thumbs-up" aria-label="Risposta utile" @click="rate(5)" />
    <UButton color="neutral" :variant="rating === 1 ? 'soft' : 'ghost'" icon="i-lucide-thumbs-down" aria-label="Risposta non utile" @click="rate(1)" />
    <UButton variant="link" :aria-expanded="expanded" @click="expanded = !expanded">Aggiungi dettagli</UButton>
    <span class="text-sm text-muted" aria-live="polite">{{ state === 'saved' ? 'Salvato' : state === 'error' ? 'Errore' : '' }}</span>
    <form v-if="expanded" class="w-full space-y-4" @submit.prevent="saveDetails">
      <UFormField label="Motivo"><USelect v-model="reason" placeholder="Seleziona" :items="[{ label: 'Risposta', value: 'answer' }, { label: 'Fonte', value: 'citation' }, { label: 'Incompleta', value: 'incomplete' }]" class="w-full" /></UFormField>
      <UFormField label="Nota opzionale"><UTextarea v-model="details" :rows="2" maxlength="2000" class="w-full" /></UFormField>
      <UButton type="submit" :loading="state === 'saving'">Salva dettagli</UButton>
    </form>
  </div>
</template>
