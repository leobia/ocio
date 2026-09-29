<script setup lang="ts">
import type { Citation, Message } from '~/types'

defineProps<{ message: Message }>()
defineEmits<{ citation: [citation: Citation] }>()
</script>

<template>
  <article class="space-y-4" :class="message.role === 'user' ? 'ml-auto max-w-[90%] rounded-lg bg-muted p-4' : ''">
    <UBadge v-if="message.status === 'ABSTAIN'" color="warning" variant="subtle">Evidenza insufficiente</UBadge>
    <p class="whitespace-pre-wrap break-words">{{ message.content }}</p>
    <UAlert v-if="message.conditions?.length" title="Condizioni" color="neutral" variant="subtle"><template #description><ul class="list-inside list-disc"><li v-for="item in message.conditions" :key="item">{{ item }}</li></ul></template></UAlert>
    <UAlert v-if="message.missing_information?.length" title="Per rispondere meglio serve" color="warning" variant="subtle"><template #description><ul class="list-inside list-disc"><li v-for="item in message.missing_information" :key="item">{{ item }}</li></ul></template></UAlert>
    <div v-if="message.citations?.length" class="flex flex-wrap gap-2" aria-label="Fonti della risposta"><UButton v-for="(citation, index) in message.citations" :key="citation.id" variant="outline" @click="$emit('citation', citation)"><span class="whitespace-normal text-left">{{ index + 1 }}. {{ citation.document_title }}</span></UButton></div>
    <FeedbackControls v-if="message.role === 'assistant'" :message-id="message.id" />
  </article>
</template>
