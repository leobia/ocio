import { expect, test } from '@playwright/test'
import { dossierSections, replaceSection } from '../app/utils/dossierSections'
import { parseTemplate } from '../app/utils/templateSections'

const narrative = 'La lavorazione si svolge su banchi dedicati. I componenti vengono preparati e assemblati secondo la sequenza descritta negli appunti.\n\n'.repeat(12)
const table = '| Attrezzatura | Impiego |\n| --- | --- |\n| Banco | Assemblaggio |\n'
const original = '# Fascicolo\n\nIntroduzione originale.\n\n## Attività\n\n' + narrative + '### Fasi\n\n- Ricezione\n- Assemblaggio\n\n' + table + '\n## Ambienti\n\nTesto **manuale**, da conservare.\n'

test('sostituisce soltanto il corpo selezionato e ignora titoli negli esempi di codice', () => {
  const markdown = original + '\n````md\n```\n## Esempio\n````\n'
  const sections = dossierSections(markdown)
  expect(sections.map(s => s.title)).toEqual(['Introduzione', 'Attività', 'Ambienti'])
  expect(parseTemplate(markdown, {}).sections.map(s => s.title)).toEqual(['Attività', 'Ambienti'])
  const edited = replaceSection(markdown, 1, 'Nuova descrizione.')
  expect(edited.slice(0, sections[1]!.bodyStart)).toBe(markdown.slice(0, sections[1]!.bodyStart))
  expect(edited.slice(edited.indexOf('## Ambienti'))).toBe(markdown.slice(markdown.indexOf('## Ambienti')))
  expect(dossierSections('## Vuota')).toHaveLength(1)
  expect(replaceSection('## Vuota', 0, 'Testo')).toBe('## Vuota\nTesto')
})

test('modifica una sezione lunga con tabella, conserva le altre e recupera un salvataggio fallito', async ({ page }) => {
  const id = '11111111-1111-4111-8111-111111111111'
  const created = '2026-09-29T10:00:00Z'
  const engagement = {
    id, company: 'Officina prova editor', site: 'Padova', reference_date: '2026-09-29', dossier_markdown: original,
    exportable_markdown: original, status: 'in_corso', version: 0, relevance: {}, relevance_history: [], proposed_facts: [],
    created_at: created, updated_at: created,
    template: { id: 'template-1', name: 'Modello personalizzato' },
    template_revision: { id: 'r1', number: 1, instructions: { Attività: 'Descrivere le fasi osservate.', Ambienti: 'Riportare il layout.' }, relevance_guidance: {} },
    history: [{ id: 'h1', number: 1, template_revision_id: 'r1', dossier_markdown: original, reason: 'creazione', created_at: created }],
    pending_migration: null,
  }
  let attempts = 0
  let releaseSave!: () => void
  const saveGate = new Promise<void>(resolve => { releaseSave = resolve })
  await page.route('**/api/v1/engagements/**', async route => {
    if (route.request().method() === 'GET') {
      if (route.request().url().endsWith('/messages')) return route.fulfill({ json: [] })
      if (route.request().url().endsWith('/review')) return route.fulfill({ json: { proposals: [], approvals: [], sources: [] } })
      if (route.request().url().endsWith('/agent')) return route.fulfill({ json: null })
      return route.fulfill({ json: engagement })
    }
    attempts++
    if (attempts === 1) {
      await saveGate
      return route.fulfill({ status: 503, json: { error: { message: 'Salvataggio non disponibile.' } } })
    }
    engagement.dossier_markdown = route.request().postDataJSON().markdown
    engagement.history.unshift({ ...engagement.history[0]!, id: 'h2', number: 2, dossier_markdown: engagement.dossier_markdown, reason: 'modifica_manuale' })
    return route.fulfill({ json: engagement })
  })
  await page.goto(`/incarichi/${id}`)
  const editor = page.getByRole('textbox', { name: 'Testo: Attività', exact: true })
  await expect(editor).toContainText('La lavorazione si svolge')
  await expect(editor.getByRole('table')).toContainText('Assemblaggio')
  await expect(page.getByRole('button', { name: 'Salva fascicolo', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Dettagli incarico', exact: true }).click()
  await expect(page.getByText('Descrivere le fasi osservate.', { exact: true })).toBeVisible()
  await editor.locator('td').first().click()
  await page.getByRole('button', { name: 'Tabella', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Aggiungi riga', exact: true }).click()
  await expect(editor.getByRole('row')).toHaveCount(3)
  await editor.getByRole('row').last().locator('td').first().fill('Avvitatore')
  await editor.locator('p:visible').first().click()
  await page.keyboard.press('Home')
  await page.keyboard.type('Nota del consulente. ')
  await page.getByRole('button', { name: '03 Ambienti', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Testo: Ambienti' })).toContainText('Testo manuale, da conservare.')
  await expect(page.getByText('Riportare il layout.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '02 Attività', exact: true }).click()
  await expect(editor).toContainText('Nota del consulente.')
  await expect(editor).toContainText('Avvitatore')
  const dialog = page.waitForEvent('dialog')
  const navigate = page.getByRole('link', { name: 'Incarichi', exact: true }).click()
  await (await dialog).dismiss()
  await navigate
  await expect(page).toHaveURL(new RegExp(id))
  await page.getByRole('button', { name: 'Salva fascicolo', exact: true }).click()
  await expect(editor).toHaveAttribute('contenteditable', 'false')
  releaseSave()
  await expect(page.getByRole('alert')).toContainText('Salvataggio non disponibile.')
  await expect(editor).toHaveAttribute('contenteditable', 'true')
  await expect(editor).toContainText('Nota del consulente.')
  await page.getByRole('button', { name: 'Salva fascicolo', exact: true }).click()
  await expect(page.getByText('Versione salvata nella cronologia.', { exact: true })).toBeVisible()
  expect(engagement.dossier_markdown).toContain('### Fasi')
  expect(engagement.dossier_markdown).toContain('Ricezione')
  expect(engagement.dossier_markdown).toContain('Avvitatore')
  expect(engagement.dossier_markdown.split('## Ambienti')[1]).toBe(original.split('## Ambienti')[1])
  expect(engagement.dossier_markdown.split('## Attività')[0]).toBe(original.split('## Attività')[0])
  await page.reload()
  await expect(editor).toContainText('Nota del consulente.')
  await expect(editor.getByRole('row')).toHaveCount(3)
  await expect(page.getByRole('button', { name: 'Salva fascicolo', exact: true })).toBeDisabled()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(editor).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('scrive più paragrafi sotto i titoli vuoti senza bloccare editor e annullamento', async ({ page }) => {
  const markdown = '## Attività\n\n### Fasi operative\n\n### Mansioni\n\n## Ambienti\n\nDa descrivere.\n'
  await page.route('**/api/v1/engagements/**', route => {
    if (route.request().url().endsWith('/messages')) return route.fulfill({ json: [] })
    if (route.request().url().endsWith('/review')) return route.fulfill({ json: { proposals: [], approvals: [], sources: [] } })
    if (route.request().url().endsWith('/agent')) return route.fulfill({ json: null })
    return route.fulfill({ json: {
    id: 'empty', company: 'Prova sezioni vuote', site: 'Padova', reference_date: '2026-09-29',
    dossier_markdown: markdown, exportable_markdown: markdown, status: 'in_corso', version: 0,
    relevance: {}, relevance_history: [], proposed_facts: [],
    template: { name: 'Modello' }, template_revision: { number: 1, instructions: {}, relevance_guidance: {} },
    history: [], pending_migration: null,
  } })
  })
  await page.goto('/incarichi/empty')
  const editor = page.getByRole('textbox', { name: 'Testo: Attività', exact: true })
  await editor.locator('p').last().click()
  await page.keyboard.type('Prima riga.')
  await page.keyboard.press('Enter')
  await page.keyboard.type('Seconda riga.')
  await expect(editor.locator('p')).toContainText(['Prima riga.', 'Seconda riga.'])
  await page.getByRole('button', { name: 'Annulla', exact: true }).click()
  await expect(editor).not.toContainText('Seconda riga.')
  await page.getByRole('button', { name: 'Ripeti', exact: true }).click()
  await expect(editor).toContainText('Seconda riga.')
  await page.getByRole('button', { name: '02 Ambienti', exact: true }).click()
  await page.getByRole('button', { name: '01 Attività', exact: true }).click()
  await expect(editor).toContainText('Prima riga.')
})

test('mostra chat e bozza, poi riprende dopo una risposta', async ({ page }) => {
  const id = '22222222-2222-4222-8222-222222222222'
  const created = '2026-09-30T10:00:00Z'
  const engagement = {
    id, company: 'Studio prova', site: 'Roma', reference_date: '2026-09-30',
    dossier_markdown: '## Attività\n\nDa completare.\n', exportable_markdown: '## Attività\n\nDa completare.\n',
    status: 'in_corso', version: 0, relevance: {}, relevance_history: [], proposed_facts: [],
    created_at: created, updated_at: created, template: { id: 'm1', name: 'Modello' },
    template_revision: { id: 'r1', number: 1, instructions: {}, relevance_guidance: {} },
    history: [], pending_migration: null,
  }
  const messages: { id: string, role: string, content: string, created_at: string, attachments: never[], observations: never[] }[] = []
  let lastRun: Record<string, any> | null = null
  let runs = 0
  await page.route('**/api/v1/engagements/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path.endsWith('/review')) return route.fulfill({ json: { proposals: [], approvals: [], sources: [] } })
    if (path.endsWith('/agent') && method === 'GET') return route.fulfill({ json: lastRun })
    if (path.endsWith('/messages') && method === 'GET') return route.fulfill({ json: messages })
    if (path.endsWith('/messages') && method === 'POST') {
      const message = { id: `u${messages.length}`, role: 'user', content: 'La sede è un ufficio.', created_at: created, attachments: [], observations: [] }
      messages.push(message)
      return route.fulfill({ status: 201, json: message })
    }
    if (path.endsWith('/agent/runs') && method === 'POST') {
      runs++
      const waiting = runs === 1
      lastRun = { id: `run-${runs}`, status: waiting ? 'in_attesa' : 'completato', model: 'gpt-4.1',
        prompt_version: 'dossier-writing-v2', template_revision_id: 'r1', plan: 'Verificare le attività.',
        questions: waiting ? [{ question: 'Qual è l’attività svolta?', impact: 5, section: 'Attività' }] : [],
        reason: 'Compilazione conclusa.', created_at: created, finished_at: created, events: [] }
      engagement.status = waiting ? 'in_attesa' : 'completato'
      if (!waiting) engagement.dossier_markdown = '## Attività\n\nLa sede è un ufficio.\n'
      engagement.version++
      messages.push({ id: `a${runs}`, role: 'assistant', content: waiting ? 'Per proseguire servono queste informazioni:\n1. Qual è l’attività svolta?' : 'Sezione aggiornata.', created_at: created, attachments: [], observations: [] })
      return route.fulfill({ json: lastRun })
    }
    return route.fulfill({ json: engagement })
  })
  await page.goto(`/incarichi/${id}`)
  await expect(page.getByRole('heading', { name: 'Studio prova' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Testo: Attività' })).toBeVisible()
  await page.getByRole('button', { name: 'Avvia compilazione' }).click()
  await expect(page.getByText('Qual è l’attività svolta?', { exact: false })).toBeVisible()
  await page.getByRole('textbox', { name: 'Messaggio e istruzioni per gli allegati' }).fill('La sede è un ufficio.')
  await page.getByRole('button', { name: "Invia all'incarico" }).click()
  await expect(page.getByRole('textbox', { name: 'Testo: Attività' })).toContainText('La sede è un ufficio.')
  expect(runs).toBe(2)
})

test('revisiona una proposta protetta e rende esportabile la revisione approvata', async ({ page }) => {
  const id = '11111111-1111-4111-8111-111111111118'
  const engagement = { id, company: 'Revisione fittizia', site: 'Roma', reference_date: '2026-10-02', dossier_markdown: '## Attività\n\nTesto manuale.', exportable_markdown: '## Attività\n\nTesto manuale.', status: 'in_corso', version: 1, relevance: {}, relevance_history: [], proposed_facts: [], created_at: '2026-10-02', updated_at: '2026-10-02', template: { id: 't', name: 'Modello' }, template_revision: { id: 'r', number: 1, instructions: {}, relevance_guidance: {} }, history: [], pending_migration: null }
  const review = { proposals: [{ id: 'p', section: 'Attività', previous: 'Testo manuale.', proposed: 'Descrizione proposta.', references: [], status: 'proposta' }], approvals: [] as { id: string, author: string, created_at: string }[], sources: [] }
  await page.route('**/api/v1/engagements/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/messages')) return route.fulfill({ json: [] })
    if (path.endsWith('/agent')) return route.fulfill({ json: null })
    if (path.endsWith('/review')) return route.fulfill({ json: review })
    if (path.endsWith('/review/p')) {
      expect(route.request().postDataJSON().action).toBe('accettata')
      engagement.dossier_markdown = '## Attività\n\nDescrizione proposta.'
      engagement.exportable_markdown = engagement.dossier_markdown
      engagement.version++
      review.proposals[0]!.status = 'accettata'
      return route.fulfill({ json: { ok: true } })
    }
    if (path.endsWith('/approvals')) {
      review.approvals.push({ id: 'approval', author: 'RSPP prova', created_at: '2026-10-02' })
      engagement.version++
      return route.fulfill({ json: { id: 'approval' } })
    }
    return route.fulfill({ json: engagement })
  })
  await page.goto(`/incarichi/${id}`)
  await expect(page.getByText('Proposta sul testo protetto', { exact: true })).toBeVisible()
  await page.getByLabel('Autore della revisione', { exact: true }).fill('RSPP prova')
  await page.getByLabel('Motivazione della revisione', { exact: true }).fill('Controllo effettuato')
  await page.getByRole('button', { name: 'Accetta sezione', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Testo: Attività', exact: true })).toContainText('Descrizione proposta.')
  await page.getByLabel('Autore della revisione', { exact: true }).fill('RSPP prova')
  await page.getByLabel('Motivazione della revisione', { exact: true }).fill('Revisione complessiva')
  await page.getByRole('button', { name: 'Approva revisione complessiva' }).click()
  await expect(page.getByRole('link', { name: 'Esporta Markdown approvato' })).toHaveAttribute('href', `/api/v1/engagements/${id}/approvals/approval/export`)
})
