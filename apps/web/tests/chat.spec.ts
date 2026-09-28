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

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Da cosa vuoi partire?' })).toBeVisible()
  await page.getByLabel('Scrivi una domanda').fill('Quale formazione è obbligatoria?')
  await page.getByRole('button', { name: 'Invia domanda' }).click()

  await expect(page.getByText('La formazione deve essere sufficiente e adeguata.')).toBeVisible()
  await expect(page.getByText('Mansione e rischi specifici del lavoratore.')).toBeVisible()
  await expect(page.getByText('La formazione varia in base ai rischi riferiti alle mansioni.')).toBeVisible()
  await page.getByRole('button', { name: /Decreto legislativo/ }).click()
  await expect(page.getByRole('complementary', { name: 'Dettaglio fonte' })).toContainText(citation.passage)
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
  await page.getByLabel('Motivo').selectOption('citation')
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

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Da cosa vuoi partire?' })).toBeVisible()
  await page.getByLabel('Scrivi una domanda').fill('Questo obbligo si applica?')
  await page.getByRole('button', { name: 'Invia domanda' }).click()
  await expect(page.getByRole('alert')).toContainText('Il servizio di risposta non è disponibile.')
  await page.getByRole('button', { name: 'Riprova' }).click()
  await expect(page.getByText('Evidenza insufficiente')).toBeVisible()
  await expect(page.getByText('Il settore di attività.')).toBeVisible()
})
