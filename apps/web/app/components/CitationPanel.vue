<script setup lang="ts">
import type { Citation } from '~/types'

const props = defineProps<{ citation: Citation | null }>()
const emit = defineEmits<{ close: [] }>()
const closeButton = ref<HTMLButtonElement>()

watch(() => props.citation, async (citation) => {
  if (citation) {
    await nextTick()
    closeButton.value?.focus()
  }
})

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.citation) emit('close')
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))

function locator(source: Citation['sources'][number]) {
  const parts = [source.partition_kind, source.partition_identifier, source.rubric].filter(Boolean)
  const coordinates = Object.entries(source.locator || {}).map(([key, value]) => `${key}: ${String(value)}`)
  return [...parts, ...coordinates].join(' · ')
}
</script>

<template>
  <Transition name="drawer">
    <aside v-if="citation" class="citation-panel" aria-label="Dettaglio fonte">
      <header class="panel-header">
        <div>
          <span class="eyebrow">Fonte verificata</span>
          <h2>{{ citation.document_title }}</h2>
        </div>
        <button ref="closeButton" class="close-button" aria-label="Chiudi dettaglio fonte" @click="$emit('close')">×</button>
      </header>

      <blockquote>{{ citation.passage }}</blockquote>

      <dl class="source-meta">
        <div><dt>Documento</dt><dd>{{ citation.document_type.replaceAll('_', ' ') }}</dd></div>
        <div v-if="citation.document_urn"><dt>URN</dt><dd>{{ citation.document_urn }}</dd></div>
        <div><dt>Vigenza</dt><dd>{{ citation.document_valid_from || 'non indicata' }} → {{ citation.document_valid_until || 'in corso' }}</dd></div>
      </dl>

      <section v-for="(source, index) in citation.sources" :key="index" class="official-source">
        <span class="eyebrow">Provenienza ufficiale</span>
        <h3>{{ source.provider || 'Fonte ufficiale' }}</h3>
        <p v-if="locator(source)" class="locator">{{ locator(source) }}</p>
        <p v-if="source.acquired_at" class="muted">Acquisita il {{ new Date(source.acquired_at).toLocaleDateString('it-IT') }}</p>
        <p v-if="source.acquisition_sha256" class="source-hash"><span>SHA-256 acquisizione</span><code>{{ source.acquisition_sha256 }}</code></p>
        <a v-if="source.url" class="source-link" :href="source.url" target="_blank" rel="noopener noreferrer">Apri la fonte ufficiale ↗</a>
      </section>
    </aside>
  </Transition>
</template>
