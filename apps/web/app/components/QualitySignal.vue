<script setup lang="ts">
import type { Engagement } from '~/types'
const props = defineProps<{ engagement: Engagement, section: string, disabled: boolean }>()
const category = ref('fatto_errato')
const detail = ref('')
const author = ref('')
const status = ref('')
const busy = ref(false)
async function send() {
  busy.value = true
  try {
    await $fetch(`/api/v1/engagements/${props.engagement.id}/quality`, { method: 'POST', body: { category: category.value, section: props.section === 'Introduzione' ? null : props.section, detail: detail.value, author: author.value, expected_version: props.engagement.version } })
    status.value = 'Segnalazione aggiunta alla inbox qualità.'; detail.value = ''
  }
  catch { status.value = 'Segnalazione non salvata. Ricarica e riprova.' }
  finally { busy.value = false }
}
</script>
<template>
  <details class="mt-4 rounded border p-4">
    <summary>Segnala un problema</summary>
    <div class="mt-3 space-y-3">
      <label class="block">Tipo di problema <select v-model="category" class="rounded border bg-default p-1"><option value="fatto_errato">Fatto errato</option><option value="omissione">Omissione</option><option value="domanda_superflua">Domanda superflua</option><option value="citazione_inadeguata">Citazione inadeguata</option></select></label>
      <UFormField label="Autore della segnalazione"><UInput v-model="author" /></UFormField>
      <UFormField label="Motivazione breve senza dati identificativi"><UTextarea v-model="detail" :maxlength="500" class="w-full" /></UFormField>
      <UButton :disabled="disabled || busy || !detail.trim() || !author.trim()" @click="send">Invia segnalazione</UButton>
      <p v-if="status" role="status">{{ status }}</p><NuxtLink to="/qualita" class="block underline">Apri inbox qualità</NuxtLink>
    </div>
  </details>
</template>
