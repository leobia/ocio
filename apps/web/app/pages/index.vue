<script setup lang="ts">
import ChatLayoutPrototype from '~/components/ChatLayoutPrototype.vue'
import type { Citation, Conversation, ConversationSummary } from '~/types'

useHead({ title: 'OCIO — Assistente normativo', htmlAttrs: { lang: 'it' } })
const api = useOcioApi()
const route = useRoute()
const chatVariant = computed(() => ['A', 'B', 'C'].includes(String(route.query.variant)) ? String(route.query.variant) : 'A')
const isPreview = computed(() => import.meta.dev && route.query.mode !== 'live')
const chatVariants = [{ key: 'A', name: 'Scrivania a tre colonne' }, { key: 'B', name: 'Conversazione focalizzata' }, { key: 'C', name: 'Contesto sopra il dialogo' }]
const conversations = ref<ConversationSummary[]>([])
const current = ref<Conversation | null>(null)
const selectedCitation = ref<Citation | null>(null)
const prompt = ref('')
const loading = ref(true)
const sending = ref(false)
const error = ref('')
const retryText = ref('')
const textarea = ref<{ textareaRef?: HTMLTextAreaElement }>()
const showContext = ref(false)

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

async function initialize() {
  if (isPreview.value) return
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
}

onMounted(initialize)
watch(isPreview, preview => { if (!preview && !current.value) void initialize() })
</script>

<template>
  <ChatLayoutPrototype v-if="isPreview" :variant="chatVariant" />
  <PrototypeShell v-else section="Assistente normativo">
    <template #sidebar>
      <UButton icon="i-lucide-plus" @click="startConversation">Nuova conversazione</UButton>
      <div class="max-h-60 space-y-2 overflow-y-auto lg:max-h-none">
        <p class="text-sm text-muted">Conversazioni</p>
        <UButton v-for="item in conversations" :key="item.id" color="neutral" :variant="current?.id === item.id ? 'soft' : 'ghost'" class="w-full justify-start" @click="openConversation(item.id)"><span class="truncate">{{ item.last_message || 'Nuova conversazione' }}</span></UButton>
      </div>
    </template>
    <template #actions><UButton v-if="!isPreview" to="/?variant=A" color="neutral" variant="outline">Confronta anteprime A/B/C</UButton><UButton v-if="chatVariant === 'B' && current?.id" color="neutral" variant="outline" :aria-expanded="showContext" @click="showContext = !showContext">{{ showContext ? 'Nascondi dati del caso' : 'Mostra dati del caso' }}</UButton></template>
    <div class="grid items-start gap-6 p-4 pb-28 sm:p-6 sm:pb-28" :class="chatVariant === 'A' && current?.id ? 'xl:grid-cols-[minmax(0,1fr)_300px]' : 'mx-auto max-w-5xl'">
      <CaseStatePanel v-if="current?.id && chatVariant === 'C'" :conversation-id="current.id" :facts="current.case_state" @updated="current.case_state = $event" />
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
        </section>
        <form v-if="current" class="sticky bottom-24 space-y-3 rounded-lg border border-default bg-default p-4" @submit.prevent="send()">
          <UFormField label="Scrivi una domanda"><UTextarea id="question" ref="textarea" v-model="prompt" :rows="3" maxlength="10000" placeholder="Chiedi a OCIO…" class="w-full" @keydown="submitOnEnter" /></UFormField>
          <div class="flex items-center justify-between gap-4"><p class="text-sm text-muted">Verifica le fonti prima di usare la risposta.</p><UButton type="submit" :disabled="!prompt.trim() || sending" :loading="sending" icon="i-lucide-arrow-up" aria-label="Invia domanda" /></div>
        </form>
      </div>
      <CaseStatePanel v-if="current?.id && (chatVariant === 'A' || (chatVariant === 'B' && showContext))" :conversation-id="current.id" :facts="current.case_state" @updated="current.case_state = $event" />
    </div>
    <CitationPanel :citation="selectedCitation" @close="selectedCitation = null" />
    <PrototypeSwitcher v-if="$route.query.mode !== 'live'" :current="chatVariant" :variants="chatVariants" />
  </PrototypeShell>
</template>
