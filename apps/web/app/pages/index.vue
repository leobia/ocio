<script setup lang="ts">
import type { Citation, Conversation, ConversationSummary } from '~/types'

useHead({ title: 'OCIO — Assistente normativo', htmlAttrs: { lang: 'it' } })
const api = useOcioApi()
const conversations = ref<ConversationSummary[]>([])
const current = ref<Conversation | null>(null)
const selectedCitation = ref<Citation | null>(null)
const prompt = ref('')
const loading = ref(true)
const sending = ref(false)
const error = ref('')
const retryText = ref('')
const textarea = ref<{ textareaRef?: HTMLTextAreaElement }>()
const chatEnd = ref<HTMLElement>()
useUnsavedChanges(computed(() => Boolean(prompt.value.trim()) && !sending.value))

function discardDraft() {
  return !prompt.value.trim() || window.confirm('La domanda non è stata inviata. Vuoi abbandonarla?')
}

async function scrollToLatest() {
  await nextTick()
  chatEnd.value?.scrollIntoView({ block: 'end', behavior: 'smooth' })
}

function newConversation(): Conversation {
  return { id: '', created_at: new Date().toISOString(), messages: [], case_state: {} }
}

async function refreshList() {
  conversations.value = await api.listConversations()
}

async function openConversation(id: string) {
  if (sending.value || loading.value || !discardDraft()) return
  error.value = ''
  loading.value = true
  try {
    current.value = await api.getConversation(id)
    prompt.value = ''
    selectedCitation.value = null
    retryText.value = ''
  }
  catch (reason) {
    error.value = (reason as Error).message
  }
  finally {
    loading.value = false
  }
}

async function startConversation() {
  if (sending.value || !discardDraft()) return
  prompt.value = ''
  retryText.value = ''
  current.value = newConversation()
  selectedCitation.value = null
  error.value = ''
  await nextTick()
  textarea.value?.textareaRef?.focus()
}

async function send(text = prompt.value.trim()) {
  if (!current.value || !text || sending.value) return
  prompt.value = ''
  retryText.value = ''
  error.value = ''
  sending.value = true
  if (!current.value.id) {
    try {
      current.value = await api.createConversation()
    }
    catch (reason) {
      error.value = (reason as Error).message
      prompt.value = text
      retryText.value = text
      sending.value = false
      return
    }
  }
  current.value.messages.push({
    id: `pending-${Date.now()}`, role: 'user', content: text, status: null,
    created_at: new Date().toISOString(),
  })
  try {
    const result = await api.sendMessage(current.value.id, text)
    result.message.citations = result.citations
    result.message.missing_information = result.missing_information
    result.message.conditions = result.conditions
    current.value.messages.push(result.message)
    try { await refreshList() }
    catch { error.value = 'Risposta ricevuta, ma la cronologia non è aggiornata. Ricarica la pagina per aggiornarla.' }
  }
  catch (reason) {
    current.value.messages = current.value.messages.filter(item => !item.id.startsWith('pending-'))
    prompt.value = text
    retryText.value = text
    error.value = (reason as Error).message
  }
  finally {
    sending.value = false
    await scrollToLatest()
  }
}

function submitOnEnter(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}

async function initialize() {
  try {
    await startConversation()
    await refreshList()
  }
  catch (reason) {
    error.value = (reason as Error).message
  }
  finally {
    loading.value = false
  }
}

onMounted(initialize)
</script>

<template>
  <AppShell section="Assistente normativo">
    <template #sidebar>
      <UButton icon="i-lucide-plus" :disabled="sending" @click="startConversation">Nuova conversazione</UButton>
      <div class="min-h-0 max-h-60 space-y-2 overflow-y-auto lg:max-h-none">
        <p class="text-sm text-muted">Conversazioni</p>
        <UButton v-for="item in conversations" :key="item.id" :disabled="sending || loading" color="neutral" :variant="current?.id === item.id ? 'soft' : 'ghost'" class="w-full justify-start" @click="openConversation(item.id)"><span class="truncate">{{ item.last_message || 'Nuova conversazione' }}</span></UButton>
      </div>
    </template>
    <div class="grid items-start gap-6 p-4 sm:p-6 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div class="min-w-0 space-y-6">
        <UAlert v-if="error" role="alert" color="error" title="Servizio non disponibile" :description="error" :actions="retryText ? [{ label: 'Riprova', onClick: () => send(retryText) }] : []" />
        <p v-if="loading" role="status">Caricamento conversazioni…</p>
        <section v-else-if="current" class="space-y-6" aria-label="Messaggi della conversazione">
          <div v-if="!current.messages.length" class="space-y-4 py-12 text-center">
            <h2 class="text-2xl font-semibold">Da cosa vuoi partire?</h2>
            <p class="text-muted">Descrivi un caso fittizio o chiedi un riferimento preciso.</p>
            <div class="flex flex-wrap justify-center gap-2"><UButton color="neutral" variant="outline" @click="prompt = 'Quali obblighi si applicano alla formazione dei lavoratori?'">Formazione dei lavoratori</UButton><UButton color="neutral" variant="outline" @click="prompt = 'Quali requisiti servono per operare in spazi confinati?'">Spazi confinati</UButton></div>
          </div>
          <ChatMessage v-for="message in current.messages" :key="message.id" :message="message" @citation="selectedCitation = $event" />
          <p v-if="sending" role="status" class="text-muted">OCIO verifica le fonti…</p>
          <div ref="chatEnd" />
        </section>
        <form v-if="current" class="sticky bottom-4 space-y-3 rounded-lg border border-default bg-default p-4" @submit.prevent="send()">
          <UFormField label="Scrivi una domanda"><UTextarea id="question" ref="textarea" v-model="prompt" :disabled="sending" :rows="3" maxlength="10000" placeholder="Chiedi a OCIO…" class="w-full" @keydown="submitOnEnter" /></UFormField>
          <div class="flex items-center justify-between gap-4"><p class="text-sm text-muted">Verifica le fonti prima di usare la risposta.</p><UButton type="submit" :disabled="!prompt.trim() || sending" :loading="sending" icon="i-lucide-arrow-up" aria-label="Invia domanda" /></div>
        </form>
      </div>
      <CaseStatePanel v-if="current?.id" :conversation-id="current.id" :facts="current.case_state" @updated="current.case_state = $event" />
      <UCard v-else as="aside"><template #header><h2 class="font-semibold">Dati del caso</h2></template><p class="text-sm text-muted">Qui raccoglierai i dati del caso dopo il primo messaggio.</p></UCard>
    </div>
    <CitationPanel :citation="selectedCitation" @close="selectedCitation = null" />
  </AppShell>
</template>
