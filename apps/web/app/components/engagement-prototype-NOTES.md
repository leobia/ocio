# Engagement UI prototype

Question: how should an RSPP navigate assignments and work on a dossier?

Chosen index: **A — compact operational list**. Chosen engagement detail: **A — document and context** (29 September).

Chosen assistant: **A — conversation with side context** (29 September). Preserve the standard Nuxt UI theme when integrating it with the real API.

Template direction: **C**, revised to let users add, rename, reorder and remove sections, each with its own agent guidance. The revised prototype still needs user validation.

Use the standard Nuxt UI theme, fonts, sizes and component proportions. Customize only the OCIO primary and neutral colors. Layout utilities organize content; they do not override component styles.

Other workflow comparisons at `/incarichi?screen=detail|create|templates|migration&variant=A|B|C`; chat at `/?variant=A|B|C`.

- Detail: full Markdown with context / individual sections / content, evidence and review tabs.
- Create: compact form / interactive steps / model first.
- Templates: editor with preview / section-specific instructions / single-column section builder with guidance per section.
- Migration: changes with checks / document comparison first / checks first.
- Chat: context beside conversation / context on demand / context above conversation.

Workflow data is local and disposable. The assistant retains its existing API calls. After selection, archive the prototypes on a temporary branch with a pointer in issue #24, then implement the chosen workflows against the API.

Chat previews now use the same fictional conversation and facts without API calls. Development `/` defaults to preview A; `/?variant=A|B|C` compares layouts. `/?mode=live` opens the real assistant. Production keeps the real assistant.
