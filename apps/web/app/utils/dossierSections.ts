/** Section offsets let the editor replace one body without rewriting the rest of the dossier. */
export function dossierSections(markdown: string) {
  const headings: { title: string, start: number, bodyStart: number }[] = []
  let fence = ''
  let offset = 0
  for (const line of markdown.split(/(?<=\n)/)) {
    const delimiter = line.match(/^ {0,3}(`{3,}|~{3,})/)
    if (delimiter) {
      const marker = delimiter[1]!
      if (!fence) fence = marker
      else if (marker[0] === fence[0] && marker.length >= fence.length && line.slice(delimiter[0].length).trim() === '') fence = ''
    }
    else if (!fence) {
      const heading = line.match(/^## (.+?)(?:\r?\n)?$/)
      if (heading) headings.push({ title: heading[1]!.trim(), start: offset, bodyStart: offset + line.length })
    }
    offset += line.length
  }
  const sections = headings.map((heading, index) => ({
    ...heading, end: headings[index + 1]?.start ?? markdown.length,
  }))
  if (!sections.length || sections[0]!.start > 0) {
    sections.unshift({ title: 'Introduzione', start: 0, bodyStart: 0, end: sections[0]?.start ?? markdown.length })
  }
  return sections
}

export function replaceSection(markdown: string, index: number, body: string) {
  const section = dossierSections(markdown)[index]
  if (!section) return markdown
  // Keep the heading and all other sections byte-for-byte; separate the following heading.
  const before = markdown.slice(0, section.bodyStart)
  return before + (before && !before.endsWith('\n') ? '\n' : '')
    + body + (section.end < markdown.length && !body.endsWith('\n\n') ? (body.endsWith('\n') ? '\n' : '\n\n') : '')
    + markdown.slice(section.end)
}
