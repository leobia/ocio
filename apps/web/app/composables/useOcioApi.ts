import type {
  Answer, CaseFact, Conversation, ConversationSummary, DossierTemplate,
  DossierTemplateRevision, Engagement, EngagementSummary,
} from '~/types'

interface ApiErrorBody {
  error?: { message?: string }
}

export function useOcioApi() {
  async function request<T>(path: string, options: Parameters<typeof $fetch<T>>[1] = {}) {
    try {
      return await $fetch<T>(`/api/v1${path}`, options)
    }
    catch (error: unknown) {
      const response = (error as { data?: ApiErrorBody }).data
      throw new Error(response?.error?.message || 'Il servizio non è raggiungibile. Riprova.')
    }
  }

  return {
    listConversations: () => request<ConversationSummary[]>('/conversations'),
    createConversation: () => request<Conversation>('/conversations', { method: 'POST' }),
    getConversation: (id: string) => request<Conversation>(`/conversations/${id}`),
    sendMessage: (id: string, content: string) => request<Answer>(
      `/conversations/${id}/messages`, { method: 'POST', body: { content } },
    ),
    updateFact: (id: string, name: string, fact: CaseFact) => request<{ case_state: Record<string, CaseFact> }>(
      `/conversations/${id}/case-state`, {
        method: 'PATCH',
        body: { facts: [{ name, value: fact.value, status: fact.status }] },
      },
    ),
    sendFeedback: (messageId: string, body: { rating?: number, reason?: string, details?: string }) => request(
      `/messages/${messageId}/feedback`, { method: 'POST', body },
    ),
    listTemplates: () => request<DossierTemplate[]>('/dossier-templates'),
    createTemplate: (body: { name: string, markdown: string, instructions: Record<string, string> }) => request<DossierTemplate>(
      '/dossier-templates', { method: 'POST', body },
    ),
    reviseTemplate: (id: string, body: { markdown: string, instructions: Record<string, string> }) => request<DossierTemplateRevision>(
      `/dossier-templates/${id}/revisions`, { method: 'POST', body },
    ),
    listEngagements: () => request<EngagementSummary[]>('/engagements'),
    createEngagement: (body: { company: string, site: string, reference_date: string, template_revision_id: string }) => request<Engagement>(
      '/engagements', { method: 'POST', body },
    ),
    getEngagement: (id: string) => request<Engagement>(`/engagements/${id}`),
    updateDossier: (id: string, markdown: string) => request<Engagement>(
      `/engagements/${id}/dossier`, { method: 'PATCH', body: { markdown } },
    ),
    applyMigration: (engagementId: string, migrationId: string) => request<Engagement>(
      `/engagements/${engagementId}/migrations/${migrationId}/apply`, { method: 'POST' },
    ),
  }
}
