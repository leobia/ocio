import { expect, test } from '@playwright/test'

test('mantiene contenuti e indicazioni quando rinomina e riordina, anche dopo un errore di salvataggio', async ({ page }) => {
  const createdAt = '2026-09-29T10:00:00Z'
  const template = {
    id: 'template-1', name: 'Modello officina', is_default: true, created_at: createdAt,
    revisions: [{ id: 'revision-1', number: 1, markdown: '# Fascicolo\n\nIntroduzione da conservare.\n\n## Identità\n\nContenuto iniziale azienda.\n\n## Macchine\n\nElenco attrezzature.\n', instructions: { Identità: 'Riporta la sede.', Macchine: 'Verifica le evidenze.' } as Record<string, string>, created_at: createdAt }],
  }
  let attempts = 0
  await page.route('**/api/v1/dossier-templates**', async (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: [template] })
    attempts++
    if (attempts === 1) return route.fulfill({ status: 503, json: { error: { message: 'Salvataggio temporaneamente non disponibile.' } } })
    const body = route.request().postDataJSON()
    const revision = { id: 'revision-2', number: 2, markdown: body.markdown, instructions: body.instructions, relevance_guidance: body.relevance_guidance, created_at: createdAt }
    template.revisions.push(revision)
    return route.fulfill({ status: 201, json: revision })
  })
  await page.goto('/modelli')
  const first = page.getByRole('region', { name: 'Sezione 1', exact: true })
  const second = page.getByRole('region', { name: 'Sezione 2', exact: true })
  await expect(first.getByLabel('Titolo della sezione')).toHaveValue('Identità')
  await first.getByLabel('Titolo della sezione').fill('Dati aziendali')
  await first.getByLabel('Descrizione della sezione').fill('Usa i documenti forniti, indica i dati mancanti.')
  await page.getByRole('button', { name: 'Sposta giù sezione 1', exact: true }).click()
  await expect(second.getByLabel('Titolo della sezione')).toHaveValue('Dati aziendali')
  await expect(second.getByLabel('Descrizione della sezione')).toHaveValue('Usa i documenti forniti, indica i dati mancanti.')
  await first.getByLabel('Titolo della sezione').fill('Dati aziendali')
  await expect(page.getByText('Ogni sezione deve avere un titolo diverso.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Crea revisione', exact: true })).toBeDisabled()
  await first.getByLabel('Titolo della sezione').fill('Macchine')
  await page.getByRole('button', { name: 'Crea revisione', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Salvataggio temporaneamente non disponibile.')
  await expect(second.getByLabel('Titolo della sezione')).toHaveValue('Dati aziendali')
  await page.getByRole('button', { name: 'Crea revisione', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Revisione 2 creata')
  await page.reload()
  await expect(second.getByLabel('Titolo della sezione')).toHaveValue('Dati aziendali')
  await expect(second.getByLabel('Descrizione della sezione')).toHaveValue('Usa i documenti forniti, indica i dati mancanti.')
  await second.getByText('Contenuto iniziale · presente', { exact: true }).click()
  await expect(second.getByLabel('Contenuto iniziale Markdown')).toHaveValue('Contenuto iniziale azienda.')
  await page.getByText('Introduzione del modello (facoltativa)', { exact: true }).click()
  await expect(page.getByLabel('Introduzione Markdown')).toHaveValue('# Fascicolo\n\nIntroduzione da conservare.')
  expect(template.revisions[1]!.instructions).not.toHaveProperty('Identità')
  expect(attempts).toBe(2)
})

test('crea un modello a sezioni e protegge le modifiche non salvate', async ({ page }) => {
  let saved: unknown
  await page.route('**/api/v1/dossier-templates', async (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: [] })
    saved = route.request().postDataJSON()
    const body = route.request().postDataJSON()
    return route.fulfill({ status: 201, json: { id: 'new-template', name: body.name, is_default: false, created_at: '2026-09-29', revisions: [{ id: 'r1', number: 1, markdown: body.markdown, instructions: body.instructions, created_at: '2026-09-29' }] } })
  })
  await page.goto('/modelli')
  await page.getByLabel('Nome del modello', { exact: true }).fill('Modello personalizzato')
  await page.getByLabel('Titolo della sezione', { exact: true }).fill('Formazione')
  await page.getByLabel('Descrizione della sezione', { exact: true }).fill('Collega gli attestati.')
  const dialog = page.waitForEvent('dialog')
  const navigation = page.getByRole('link', { name: 'Incarichi', exact: true }).click()
  await (await dialog).dismiss()
  await navigation
  await expect(page).toHaveURL(/\/modelli$/)
  await expect(page.getByLabel('Titolo della sezione', { exact: true })).toHaveValue('Formazione')
  await page.getByRole('button', { name: 'Crea modello', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Modello creato')
  expect(saved).toEqual({ name: 'Modello personalizzato', markdown: '## Formazione\n', instructions: { Formazione: 'Collega gli attestati.' }, relevance_guidance: {} })
})
