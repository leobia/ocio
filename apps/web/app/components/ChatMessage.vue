<script setup lang="ts">
import type { Citation, Message } from '~/types'

defineProps<{ message: Message }>()
defineEmits<{ citation: [citation: Citation] }>()
</script>

<template>
  <article :class="['message', message.role, { abstention: message.status === 'ABSTAIN' }]">
    <div v-if="message.role === 'assistant'" class="assistant-mark">O</div>
    <div class="message-body">
      <div v-if="message.status === 'ABSTAIN'" class="answer-status">Evidenza insufficiente</div>
      <p class="message-text">{{ message.content }}</p>

      <div v-if="message.conditions?.length" class="notice conditions">
        <strong>Condizioni</strong>
        <ul><li v-for="item in message.conditions" :key="item">{{ item }}</li></ul>
      </div>
      <div v-if="message.missing_information?.length" class="notice missing">
        <strong>Per rispondere meglio serve</strong>
        <ul><li v-for="item in message.missing_information" :key="item">{{ item }}</li></ul>
      </div>

      <div v-if="message.citations?.length" class="citations" aria-label="Fonti della risposta">
        <button v-for="(citation, index) in message.citations" :key="citation.id" @click="$emit('citation', citation)">
          <span>{{ index + 1 }}</span>{{ citation.document_title }}
        </button>
      </div>
      <FeedbackControls v-if="message.role === 'assistant'" :message-id="message.id" />
    </div>
  </article>
</template>
