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

export interface DossierTemplateRevision {
  id: string
  number: number
  markdown: string
  instructions: Record<string, string>
  relevance_guidance: Record<string, string>
  created_at: string
}

export interface DossierTemplate {
  id: string
  name: string
  is_default: boolean
  created_at: string
  revisions: DossierTemplateRevision[]
}

export interface EngagementSummary {
  id: string
  company: string
  site: string
  reference_date: string
  created_at: string
  template_name: string
  template_revision: number
  has_pending_migration: boolean
}

export interface DossierHistory {
  id: string
  number: number
  template_revision_id: string
  dossier_markdown: string
  reason: 'creazione' | 'modifica_manuale' | 'migrazione' | 'agente'
  created_at: string
}

export interface DossierMigration {
  id: string
  source_revision_id: string
  target_revision_id: string
  target_revision: number
  proposed_markdown: string
  diff: string
  created_at: string
}

export interface Engagement {
  id: string
  company: string
  site: string
  reference_date: string
  dossier_markdown: string
  status: 'in_corso' | 'in_attesa' | 'completato' | 'fallito'
  version: number
  relevance: Record<string, { status: 'da_valutare' | 'pertinente' | 'non_pertinente' | 'da_chiarire', reason: string, references: string[], origin: 'sistema' | 'agente' | 'operatore' }>
  relevance_history: { id: string, run_id: string | null, section: string, status: string, reason: string, references: string[], origin: string, created_at: string }[]
  proposed_facts: { id: string, run_id: string, section: string, text: string, references: string[], created_at: string }[]
  exportable_markdown: string
  created_at: string
  updated_at: string
  template: { id: string, name: string }
  template_revision: { id: string, number: number, instructions: Record<string, string>, relevance_guidance: Record<string, string> }
  history: DossierHistory[]
  pending_migration: DossierMigration | null
}

export interface EngagementAttachment {
  id: string
  name: string
  media_type: string
  instruction: string
  size: number
  status: 'in_attesa' | 'analizzato' | 'errore'
  error: string | null
}

export interface EngagementObservation {
  id: string
  attachment_id: string | null
  section: string | null
  information: string
  status: 'osservato' | 'non_leggibile' | 'non_determinabile'
  text: string
  position: string | null
  instruction: string
  method: string
  version: string
}

export interface EngagementMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  attachments: EngagementAttachment[]
  observations: EngagementObservation[]
}

export interface DossierAgentRun {
  id: string
  status: 'in_corso' | 'in_attesa' | 'completato' | 'fallito'
  model: string
  prompt_version: string
  template_revision_id: string
  plan: string
  questions: { question: string, impact: number, section: string | null }[]
  reason: string
  created_at: string
  finished_at: string | null
  events: { type: string, data: Record<string, unknown>, created_at: string }[]
}
