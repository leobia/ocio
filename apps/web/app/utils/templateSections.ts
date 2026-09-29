import { dossierSections } from './dossierSections'

export interface TemplateSection {
  id: number
  title: string
  body: string
  instruction: string
}

// Match the API's level-two Markdown sections; preserve the preamble and section content.
export function parseTemplate(markdown: string, instructions: Record<string, string>) {
  const headings = dossierSections(markdown).filter(section => section.bodyStart > 0)
  return {
    preamble: markdown.slice(0, headings[0]?.start ?? markdown.length).trimEnd(),
    sections: headings.map((heading, index): TemplateSection => ({
      id: index + 1,
      title: heading.title,
      body: markdown.slice(heading.bodyStart, heading.end).replace(/^\n+|\n+$/g, ''),
      instruction: instructions[heading.title] || '',
    })),
  }
}

export function serializeTemplate(preamble: string, sections: TemplateSection[]) {
  return {
    markdown: [preamble.trimEnd(), ...sections.map(section => `## ${section.title.trim()}\n\n${section.body}`.trimEnd())].filter(Boolean).join('\n\n') + '\n',
    instructions: Object.fromEntries(sections.filter(section => section.instruction.trim()).map(section => [section.title.trim(), section.instruction])),
  }
}
