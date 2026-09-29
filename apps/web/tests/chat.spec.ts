import { expect, test, type Page, type Route } from '@playwright/test'

const conversationId = '11111111-1111-4111-8111-111111111111'
const assistantId = '22222222-2222-4222-8222-222222222222'
const createdAt = '2026-09-28T10:00:00Z'
const citation = {
  id: '33333333-3333-4333-8333-333333333333',
  passage: 'Il datore di lavoro assicura che ciascun lavoratore riceva una formazione sufficiente ed adeguata.',
  document_title: 'Decreto legislativo 9 aprile 2008, n. 81',
  document_type: 'atto_normativo',
  document_urn: 'urn:nir:stato:decreto.legislativo:2008-04-09;81',
  document_valid_from: '2008-05-15',
  document_valid_until: null,
  sources: [{
    partition_identifier: 'art-37-comma-1', partition_kind: 'comma',
    rubric: 'Formazione dei lavoratori', locator: { articolo: 37, comma: 1 },
    provider: 'Normattiva', url: 'https://www.normattiva.it/',
    acquired_at: '2026-09-20T08:00:00Z',
  }],
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

test('crea una conversazione e rende verificabili risposta, stato e feedback', async ({ page }) => {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/conversations' && route.request().method() === 'GET') return json(route, [])
    if (path === '/api/v1/conversations' && route.request().method() === 'POST') {
      return json(route, { id: conversationId, created_at: createdAt, messages: [], case_state: {} }, 201)
    }
    if (path.endsWith('/messages') && path.includes(conversationId)) return json(route, {
      status: 'ANSWER',
      message: { id: assistantId, role: 'assistant', content: 'La formazione deve essere sufficiente e adeguata.', status: 'ANSWER', created_at: createdAt },
      citations: [citation],
      conditions: ['La formazione varia in base ai rischi riferiti alle mansioni.'],
      missing_information: ['Mansione e rischi specifici del lavoratore.'],
    }, 201)
    if (path.endsWith('/case-state')) return json(route, {
      case_state: { employee_count: { value: 12, status: 'confirmed', source_message_id: null } },
    })
    if (path.endsWith('/feedback')) return json(route, {
      message_id: assistantId, rating: 5, reason: null, details: null, updated_at: createdAt,
    })
    return json(route, { error: { message: `Unexpected request: ${path}` } }, 404)
  })

  await page.goto('/?mode=live')
  await expect(page.getByRole('heading', { name: 'Da cosa vuoi partire?' })).toBeVisible()
  await page.getByLabel('Scrivi una domanda').fill('Quale formazione è obbligatoria?')
  await page.getByRole('button', { name: 'Invia domanda' }).click()

  await expect(page.getByText('La formazione deve essere sufficiente e adeguata.')).toBeVisible()
  await expect(page.getByText('Mansione e rischi specifici del lavoratore.')).toBeVisible()
  await expect(page.getByText('La formazione varia in base ai rischi riferiti alle mansioni.')).toBeVisible()
  await page.getByRole('button', { name: /Decreto legislativo/ }).click()
  await expect(page.getByRole('dialog', { name: citation.document_title })).toContainText(citation.passage)
  await expect(page.getByRole('link', { name: /Apri la fonte ufficiale/ })).toHaveAttribute('href', 'https://www.normattiva.it/')
  await page.getByRole('button', { name: 'Chiudi dettaglio fonte' }).click()

  await page.getByRole('button', { name: 'Aggiungi dato' }).click()
  await page.getByLabel('Nome').fill('employee_count')
  await page.getByLabel('Valore').fill('12')
  await page.getByRole('button', { name: 'Salva', exact: true }).click()
  await expect(page.getByText('employee count')).toBeVisible()

  await page.getByRole('button', { name: 'Risposta utile' }).click()
  await expect(page.getByText('Salvato')).toBeVisible()
  await page.getByRole('button', { name: 'Aggiungi dettagli' }).click()
  await page.getByLabel('Motivo').click()
  await page.getByRole('option', { name: 'Fonte', exact: true }).click()
  await page.getByLabel('Nota opzionale').fill('Fonte chiara e pertinente.')
  await page.getByRole('button', { name: 'Salva dettagli' }).click()
  await expect(page.getByText('Salvato')).toBeVisible()
})

test('distingue astensione e consente retry dopo un errore provider', async ({ page }) => {
  let attempts = 0
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/conversations' && route.request().method() === 'GET') return json(route, [])
    if (path === '/api/v1/conversations' && route.request().method() === 'POST') {
      return json(route, { id: conversationId, created_at: createdAt, messages: [], case_state: {} }, 201)
    }
    if (path.endsWith('/messages')) {
      attempts += 1
      if (attempts === 1) {
        return json(route, { error: { code: 'provider_failure', message: 'Il servizio di risposta non è disponibile.' } }, 502)
      }
      return json(route, {
        status: 'ABSTAIN',
        message: { id: assistantId, role: 'assistant', content: 'Non ci sono elementi sufficienti per rispondere.', status: 'ABSTAIN', created_at: createdAt },
        citations: [], conditions: [], missing_information: ['Il settore di attività.'],
      }, 201)
    }
    return json(route, { error: { message: `Unexpected request: ${path}` } }, 404)
  })

  await page.goto('/?mode=live')
  await expect(page.getByRole('heading', { name: 'Da cosa vuoi partire?' })).toBeVisible()
  await page.getByLabel('Scrivi una domanda').fill('Questo obbligo si applica?')
  await page.getByRole('button', { name: 'Invia domanda' }).click()
  await expect(page.getByRole('alert')).toContainText('Il servizio di risposta non è disponibile.')
  await page.getByRole('button', { name: 'Riprova' }).click()
  await expect(page.getByText('Evidenza insufficiente')).toBeVisible()
  await expect(page.getByText('Il settore di attività.')).toBeVisible()
})

test('crea un incarico e applica una migrazione visibile senza perdere il testo', async ({ page }) => {
  const templateId = '44444444-4444-4444-8444-444444444444'
  const revision1 = '55555555-5555-4555-8555-555555555555'
  const revision2 = '66666666-6666-4666-8666-666666666666'
  const migrationId = '77777777-7777-4777-8777-777777777777'
  const schema = '# Fascicolo\n\n## Identità\n\n## Macchine\n'
  let templates = [{
    id: templateId, name: 'Fascicolo sicurezza aziendale', is_default: true, created_at: createdAt,
    revisions: [{ id: revision1, number: 1, markdown: schema, instructions: { Macchine: 'Elencare le attrezzature.' }, created_at: createdAt }],
  }]
  let summaries: unknown[] = []
  let engagement: Record<string, any> | null = null

  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path === '/api/v1/dossier-templates' && method === 'GET') return json(route, templates)
    if (path === '/api/v1/engagements' && method === 'GET') return json(route, summaries)
    if (path === '/api/v1/engagements' && method === 'POST') {
      engagement = {
        id: conversationId, company: 'Officina esempio', site: 'Sede nord', reference_date: '2026-09-29',
        dossier_markdown: schema, created_at: createdAt, updated_at: createdAt,
        template: { id: templateId, name: templates[0]!.name },
        template_revision: { id: revision1, number: 1, instructions: templates[0]!.revisions[0]!.instructions },
        history: [{ id: assistantId, number: 1, template_revision_id: revision1, dossier_markdown: schema, reason: 'creazione', created_at: createdAt }],
        pending_migration: null,
      }
      summaries = [{ id: conversationId, company: 'Officina esempio', site: 'Sede nord', reference_date: '2026-09-29', created_at: createdAt, template_name: templates[0]!.name, template_revision: 1, has_pending_migration: false }]
      return json(route, engagement, 201)
    }
    if (path === `/api/v1/engagements/${conversationId}` && method === 'GET') return json(route, engagement)
    if (path.endsWith('/dossier') && method === 'PATCH') {
      const body = route.request().postDataJSON()
      engagement!.dossier_markdown = body.markdown
      engagement!.history.unshift({ id: citation.id, number: 2, template_revision_id: revision1, dossier_markdown: body.markdown, reason: 'modifica_manuale', created_at: createdAt })
      return json(route, engagement)
    }
    if (path === `/api/v1/dossier-templates/${templateId}/revisions` && method === 'POST') {
      const body = route.request().postDataJSON()
      const revision = { id: revision2, number: 2, markdown: body.markdown, instructions: body.instructions, created_at: createdAt }
      templates = [{ ...templates[0]!, revisions: [...templates[0]!.revisions, revision] }]
      engagement!.pending_migration = {
        id: migrationId, source_revision_id: revision1, target_revision_id: revision2, target_revision: 2,
        proposed_markdown: `${engagement!.dossier_markdown}\n## Formazione\n`,
        diff: '+## Formazione\n', created_at: createdAt,
      }
      return json(route, revision, 201)
    }
    if (path.endsWith(`/migrations/${migrationId}/apply`) && method === 'POST') {
      engagement!.dossier_markdown = engagement!.pending_migration.proposed_markdown
      engagement!.template_revision = { id: revision2, number: 2, instructions: { Formazione: 'Indicare attestati.' } }
      engagement!.pending_migration = null
      return json(route, engagement)
    }
    return json(route, { error: { message: `Unexpected request: ${method} ${path}` } }, 404)
  })

  await page.goto('/incarichi')
  await expect(page.getByText('Crea un incarico oppure aprine uno esistente.')).toBeVisible()
  await page.getByRole('button', { name: 'Nuovo incarico' }).click()
  await page.getByLabel('Azienda', { exact: true }).fill('Officina esempio')
  await page.getByLabel('Sede', { exact: true }).fill('Sede nord')
  await page.getByLabel('Data di riferimento', { exact: true }).fill('2026-09-29')
  await page.getByRole('button', { name: 'Crea incarico' }).click()
  await expect(page.getByRole('heading', { name: 'Officina esempio' })).toBeVisible()

  const dossier = page.getByLabel('Fascicolo Markdown')
  await dossier.fill(`${schema}\nTesto manuale approvato.`)
  await page.getByRole('button', { name: 'Salva fascicolo' }).click()
  await expect(page.getByText('Versione salvata nella cronologia.')).toBeVisible()

  await page.getByRole('button', { name: 'Modelli fascicolo' }).click()
  await page.getByLabel('Schema Markdown').fill(`${schema}\n## Formazione\n`)
  await page.getByLabel('Formazione').fill('Indicare attestati.')
  await page.getByRole('button', { name: 'Crea revisione' }).click()
  await page.getByRole('button', { name: 'Incarichi', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Passa alla revisione 2' })).toBeVisible()
  await page.getByRole('button', { name: 'Applica migrazione' }).click()
  await expect(page.getByText('Fascicolo sicurezza aziendale · revisione 2')).toBeVisible()
  await expect(dossier).toHaveValue(/Testo manuale approvato[\s\S]*## Formazione/)
})
