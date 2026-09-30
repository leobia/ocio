<script setup lang="ts">
import type { EngagementMessage } from '~/types'

const props = defineProps<{
  engagementId: string
  messages: EngagementMessage[]
  sections: string[]
}>()
const emit = defineEmits<{
  sent: [message: EngagementMessage]
  link: [observationId: string, section: string | null]
}>()
const api = useOcioApi()
const sending = ref(false)
const error = ref('')
const content = ref('')
const files = ref<File[]>([])
const fileInstructions = ref<string[]>([])
const picker = ref<HTMLInputElement>()

async function submit() {
  if (sending.value || (!content.value.trim() && !files.value.length)) return
  sending.value = true
  error.value = ''
  const body = new FormData()
  body.append('content', content.value)
  for (const [index, file] of files.value.entries()) {
    body.append('files', file)
    body.append('file_instructions', fileInstructions.value[index] || '')
  }
  try {
    const message = await api.sendEngagementMessage(props.engagementId, body)
    emit('sent', message)
    content.value = ''
    files.value = []
    fileInstructions.value = []
    if (picker.value) picker.value.value = ''
  }
  catch (reason) { error.value = (reason as Error).message }
  finally { sending.value = false }
}

function updateFiles(event: Event) {
  files.value = Array.from((event.target as HTMLInputElement).files || [])
  fileInstructions.value = files.value.map(() => '')
}
</script>

<template>
  <section class="mx-auto max-w-4xl space-y-5" aria-label="Chat dell'incarico">
    <div>
      <h3 class="text-xl font-semibold">Materiale e osservazioni</h3>
      <p class="text-sm text-muted">Invia appunti, foto o documenti con una richiesta mirata. Le osservazioni restano collegate agli originali.</p>
    </div>
    <p v-if="!messages.length" class="rounded-lg border border-dashed p-6 text-sm text-muted">Nessun materiale acquisito per questo incarico.</p>
    <article v-for="message in messages" :key="message.id" class="rounded-lg border p-4 space-y-4">
      <div class="flex items-start justify-between gap-3">
        <UBadge :color="message.role === 'assistant' ? 'primary' : 'neutral'" variant="subtle">{{ message.role === 'assistant' ? 'OCIO' : 'Operatore' }}</UBadge>
        <p class="whitespace-pre-wrap break-words">{{ message.content || 'Allegati con istruzioni dedicate' }}</p>
        <time class="shrink-0 text-xs text-muted">{{ new Date(message.created_at).toLocaleString('it-IT') }}</time>
      </div>
      <ul v-if="message.attachments.length" class="space-y-2">
        <li v-for="attachment in message.attachments" :key="attachment.id" class="flex flex-wrap items-center gap-2 rounded-md bg-muted p-2 text-sm">
          <a class="underline" :href="api.attachmentUrl(engagementId, attachment.id)">{{ attachment.name }}</a>
          <span class="text-xs text-muted">{{ Math.ceil(attachment.size / 1024) }} KB</span>
          <p v-if="attachment.instruction" class="w-full text-xs text-muted">Istruzione: {{ attachment.instruction }}</p>
          <UBadge :color="attachment.status === 'errore' ? 'error' : attachment.status === 'analizzato' ? 'success' : 'neutral'" variant="subtle">{{ attachment.status === 'errore' ? 'Analisi fallita' : attachment.status === 'analizzato' ? 'Analizzato' : 'In attesa' }}</UBadge>
          <span v-if="attachment.error" role="alert" class="w-full text-error">{{ attachment.error }}</span>
        </li>
      </ul>
      <div v-if="message.observations.length" class="space-y-3 border-t pt-3">
        <h4 class="text-sm font-semibold">Osservazioni</h4>
        <div v-for="observation in message.observations" :key="observation.id" class="rounded-md bg-muted p-3 text-sm">
          <div class="flex flex-wrap items-center gap-2"><strong>{{ observation.information }}</strong><UBadge :color="observation.status === 'osservato' ? 'success' : 'warning'" variant="subtle">{{ observation.status.replaceAll('_', ' ') }}</UBadge><span v-if="observation.position" class="text-muted">{{ observation.position }}</span></div>
          <p class="mt-1 whitespace-pre-wrap">{{ observation.text }}</p>
          <div class="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted"><span>{{ observation.method }} · {{ observation.version }}</span><label :for="`section-${observation.id}`">Sezione</label><select :id="`section-${observation.id}`" class="rounded border bg-default p-1 text-sm" :value="observation.section || ''" @change="emit('link', observation.id, ($event.target as HTMLSelectElement).value || null)"><option value="">Nessuna</option><option v-for="section in sections" :key="section" :value="section">{{ section }}</option></select></div>
        </div>
      </div>
    </article>
    <form class="space-y-3 rounded-lg border p-4" @submit.prevent="submit">
      <UAlert v-if="error" role="alert" color="error" :title="error" />
      <UFormField label="Messaggio e istruzioni per gli allegati"><UTextarea v-model="content" :rows="4" :disabled="sending" placeholder="Cosa vuoi che OCIO osservi o estragga?" class="w-full" /></UFormField>
      <UFormField label="Foto e documenti"><input ref="picker" type="file" multiple accept="image/jpeg,image/png,image/webp,application/pdf,text/plain" :disabled="sending" @change="updateFiles"></UFormField>
      <div v-for="(file, index) in files" :key="`${file.name}-${index}`" class="space-y-1"><label class="block text-sm" :for="`file-instruction-${index}`">Istruzione per {{ file.name }} <span class="text-muted">(facoltativa; altrimenti usa il messaggio)</span></label><input :id="`file-instruction-${index}`" v-model="fileInstructions[index]" type="text" maxlength="10000" :disabled="sending" class="w-full rounded border bg-default p-2" placeholder="Es. leggi la targhetta di questa foto"></div>
      <p v-if="files.length" class="text-xs text-muted">{{ files.length }} file selezionati · massimo 5 file da 10 MB ciascuno</p>
      <UButton type="submit" :loading="sending" :disabled="sending || (!content.trim() && !files.length)">Invia all'incarico</UButton>
    </form>
  </section>
</template>
