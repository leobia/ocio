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
    created_at: created, updated_at: created,
    template: { id: 'template-1', name: 'Modello personalizzato' },
    template_revision: { id: 'r1', number: 1, instructions: { Attività: 'Descrivere le fasi osservate.', Ambienti: 'Riportare il layout.' } },
    history: [{ id: 'h1', number: 1, template_revision_id: 'r1', dossier_markdown: original, reason: 'creazione', created_at: created }],
    pending_migration: null,
  }
  let attempts = 0
  let releaseSave!: () => void
  const saveGate = new Promise<void>(resolve => { releaseSave = resolve })
  await page.route('**/api/v1/engagements/**', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: engagement })
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
  await page.getByRole('button', { name: 'Aggiungi riga', exact: true }).click()
  await expect(editor.getByRole('row')).toHaveCount(3)
  await editor.getByRole('row').last().locator('td').first().fill('Avvitatore')
  await editor.locator('p').first().click()
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
