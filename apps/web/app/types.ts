export interface CitationSource {
  partition_identifier?: string
  partition_kind?: string
  rubric?: string | null
  locator?: Record<string, unknown>
  valid_from?: string | null
  valid_until?: string | null
  provider?: string
  url?: string
  acquired_at?: string
  acquisition_sha256?: string
}

export interface Citation {
  id: string
  passage: string
  document_title: string
  document_type: string
  document_urn?: string | null
  document_valid_from?: string | null
  document_valid_until?: string | null
  sources: CitationSource[]
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: 'ANSWER' | 'ABSTAIN' | null
  created_at: string
  citations?: Citation[]
  missing_information?: string[]
  conditions?: string[]
}

export interface CaseFact {
  value: string | number | boolean | string[] | null
  status: 'confirmed' | 'inferred' | 'unknown'
  source_message_id?: string | null
  updated_at?: string
}

export interface Conversation {
  id: string
  created_at: string
  messages: Message[]
  case_state: Record<string, CaseFact>
}

export interface ConversationSummary {
  id: string
  created_at: string
  message_count: number
  last_message: string | null
}

export interface Answer {
  status: 'ANSWER' | 'ABSTAIN'
  message: Message
  citations: Citation[]
  missing_information: string[]
  conditions: string[]
}
