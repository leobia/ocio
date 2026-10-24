import { expect, test } from '@playwright/test'

test('classifica un candidato e revoca una decisione conservando la cronologia', async ({ page }) => {
  const item = { id: 'candidate', engagement_id: 'case', run_id: 'run', revision_id: 'revision', section: 'Attività', category: 'omissione', detail: 'Manca un dettaglio degli appunti.', author: 'Operatore', cause: null, status: 'aperto', created_at: '2026-10-02' }
  const events: Record<string, unknown>[] = []
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/quality') return route.fulfill({ json: [item] })
    if (path.endsWith('/history')) return route.fulfill({ json: events })
    if (path === '/api/v1/engagements/case') return route.fulfill({ json: { version: 3 } })
    if (path === '/api/v1/quality/candidate') {
      const value = route.request().postDataJSON()
      item.status = value.action
      events.push({ author: value.author, reason: value.reason, scope: value.action, cause: value.cause, versions: {}, created_at: '2026-10-02' })
      return route.fulfill({ json: { ok: true } })
    }
    return route.fulfill({ status: 404, json: {} })
  })
  await page.goto('/qualita')
  await page.getByRole('button', { name: /omissione/ }).click()
  await expect(page.getByRole('link', { name: 'Apri incarico ed evidenze' })).toHaveAttribute('href', '/incarichi/case')
  await page.getByLabel('Responsabile della decisione').fill('Responsabile prova')
  await page.getByLabel('Motivazione della decisione').fill('Segnalazione duplicata')
  await page.getByRole('button', { name: 'Salva decisione' }).click()
  await expect(page.getByRole('button', { name: /omissione · scartato/ })).toBeVisible()
  await page.getByLabel('Motivazione della decisione').fill('Riaperta per nuova verifica')
  await page.getByRole('button', { name: 'Salva decisione' }).click()
  await expect(page.getByRole('button', { name: /omissione · aperto/ })).toBeVisible()
  await page.getByText('Cronologia delle decisioni', { exact: true }).click()
  await expect(page.getByText('Segnalazione duplicata', { exact: true })).toBeVisible()
  await expect(page.getByText('Riaperta per nuova verifica', { exact: true })).toBeVisible()
})
