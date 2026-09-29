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
const textarea = ref<HTMLTextAreaElement>()

function newConversation(): Conversation {
  return { id: '', created_at: new Date().toISOString(), messages: [], case_state: {} }
}

async function refreshList() {
  conversations.value = await api.listConversations()
}

async function openConversation(id: string) {
  error.value = ''
  loading.value = true
  try {
    current.value = await api.getConversation(id)
  }
  catch (reason) {
    error.value = (reason as Error).message
  }
  finally {
    loading.value = false
  }
}

async function startConversation() {
  current.value = newConversation()
  selectedCitation.value = null
  error.value = ''
  await nextTick()
  textarea.value?.focus()
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
    await refreshList()
  }
  catch (reason) {
    current.value.messages = current.value.messages.filter(item => !item.id.startsWith('pending-'))
    prompt.value = text
    retryText.value = text
    error.value = (reason as Error).message
  }
  finally {
    sending.value = false
  }
}

function submitOnEnter(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

onMounted(async () => {
  try {
    await refreshList()
    await startConversation()
  }
  catch (reason) {
    error.value = (reason as Error).message
  }
  finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="app-shell">
    <nav class="conversation-nav" aria-label="Conversazioni">
      <a class="brand" href="/" aria-label="OCIO home"><span>O</span><strong>OCIO</strong></a>
      <NuxtLink class="section-link" to="/incarichi">Incarichi e fascicoli</NuxtLink>
      <button class="new-chat" @click="startConversation"><span>＋</span> Nuova conversazione</button>
      <div class="history-label">Conversazioni</div>
      <div class="conversation-list">
        <button v-for="item in conversations" :key="item.id" :class="{ active: current?.id === item.id }" @click="openConversation(item.id)">
          <strong>{{ item.last_message || 'Nuova conversazione' }}</strong>
          <small>{{ item.message_count }} messaggi · {{ new Date(item.created_at).toLocaleDateString('it-IT') }}</small>
        </button>
      </div>
      <div class="scope-note"><span>α</span><p><strong>Alpha interna</strong>Usa solo casi aziendali fittizi.</p></div>
    </nav>

    <main class="workspace">
      <header class="workspace-header">
        <div><span class="eyebrow">Assistente normativo</span><h1>{{ current ? 'Verifica il tuo caso' : 'OCIO' }}</h1></div>
        <div class="corpus-status"><i /> Corpus corrente</div>
      </header>

      <div v-if="error" class="global-error" role="alert">
        <span>{{ error }}</span><button v-if="retryText" @click="send(retryText)">Riprova</button>
      </div>

      <section v-if="loading" class="center-state" aria-live="polite"><div class="loader" />Caricamento conversazioni…</section>
      <section v-else-if="current" class="chat" aria-label="Messaggi della conversazione">
        <div v-if="!current.messages.length" class="chat-empty">
          <span class="welcome-mark small">O</span>
          <h2>Da cosa vuoi partire?</h2>
          <p>Descrivi un caso fittizio o chiedi un riferimento preciso.</p>
          <div class="suggestions">
            <button @click="prompt = 'Quali obblighi si applicano alla formazione dei lavoratori?'">Formazione dei lavoratori</button>
            <button @click="prompt = 'Quali requisiti servono per operare in spazi confinati?'">Spazi confinati</button>
          </div>
        </div>
        <ChatMessage v-for="message in current.messages" :key="message.id" :message="message" @citation="selectedCitation = $event" />
        <div v-if="sending" class="thinking" aria-live="polite"><span /><span /><span /> OCIO verifica le fonti</div>
      </section>

      <form v-if="current" class="composer" @submit.prevent="send()">
        <label class="sr-only" for="question">Scrivi una domanda</label>
        <textarea id="question" ref="textarea" v-model="prompt" rows="1" maxlength="10000" placeholder="Chiedi a OCIO…" @keydown="submitOnEnter" />
        <button type="submit" :disabled="!prompt.trim() || sending" aria-label="Invia domanda">↑</button>
        <small>Le risposte non sostituiscono il giudizio professionale. Verifica sempre le fonti.</small>
      </form>
    </main>

    <CaseStatePanel v-if="current?.id" :conversation-id="current.id" :facts="current.case_state" @updated="current.case_state = $event" />
    <CitationPanel :citation="selectedCitation" @close="selectedCitation = null" />
  </div>
</template>
