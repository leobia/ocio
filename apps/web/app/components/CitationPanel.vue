<script setup lang="ts">
import type { Citation } from '~/types'

const props = defineProps<{ citation: Citation | null }>()
const emit = defineEmits<{ close: [] }>()
function locator(source: Citation['sources'][number]) {
  const parts = [source.partition_kind, source.partition_identifier, source.rubric].filter(Boolean)
  const coordinates = Object.entries(source.locator || {}).map(([key, value]) => `${key}: ${String(value)}`)
  return [...parts, ...coordinates].join(' · ')
}
</script>

<template>
  <USlideover :open="Boolean(citation)" :title="citation?.document_title || 'Dettaglio fonte'" description="Passaggio e provenienza della fonte" @update:open="value => { if (!value) emit('close') }">
    <template #close><UButton color="neutral" variant="ghost" icon="i-lucide-x" aria-label="Chiudi dettaglio fonte" /></template>
    <template #body>
      <div v-if="citation" class="space-y-6">
        <blockquote class="border-l-2 border-primary pl-4 whitespace-pre-wrap">{{ citation.passage }}</blockquote>
        <dl class="space-y-4"><div><dt class="text-sm text-muted">Documento</dt><dd>{{ citation.document_type.replaceAll('_', ' ') }}</dd></div><div v-if="citation.document_urn"><dt class="text-sm text-muted">URN</dt><dd class="break-all">{{ citation.document_urn }}</dd></div><div><dt class="text-sm text-muted">Vigenza</dt><dd>{{ citation.document_valid_from || 'non indicata' }} → {{ citation.document_valid_until || 'in corso' }}</dd></div></dl>
        <UCard v-for="(source, index) in citation.sources" :key="index">
          <template #header><h3 class="font-semibold">{{ source.provider || 'Fonte ufficiale' }}</h3></template>
          <div class="space-y-3 text-sm"><p v-if="locator(source)">{{ locator(source) }}</p><p v-if="source.acquired_at" class="text-muted">Acquisita il {{ new Date(source.acquired_at).toLocaleDateString('it-IT') }}</p><p v-if="source.acquisition_sha256" class="break-all text-muted">SHA-256: {{ source.acquisition_sha256 }}</p><UButton v-if="source.url" :to="source.url" target="_blank" rel="noopener noreferrer" variant="link">Apri la fonte ufficiale ↗</UButton></div>
        </UCard>
      </div>
    </template>
  </USlideover>
</template>
