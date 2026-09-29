export interface TemplateSection {
  id: number
  title: string
  body: string
  instruction: string
}

// Match the API's level-two Markdown sections; preserve the preamble and section content.
export function parseTemplate(markdown: string, instructions: Record<string, string>) {
  const headings = [...markdown.matchAll(/^## (.+)$/gm)]
  return {
    preamble: markdown.slice(0, headings[0]?.index ?? markdown.length).trimEnd(),
    sections: headings.map((heading, index): TemplateSection => ({
      id: index + 1,
      title: heading[1]!.trim(),
      body: markdown.slice(heading.index! + heading[0].length, headings[index + 1]?.index ?? markdown.length).replace(/^\n+|\n+$/g, ''),
      instruction: instructions[heading[1]!.trim()] || '',
    })),
  }
}

export function serializeTemplate(preamble: string, sections: TemplateSection[]) {
  return {
    markdown: [preamble.trimEnd(), ...sections.map(section => `## ${section.title.trim()}\n\n${section.body}`.trimEnd())].filter(Boolean).join('\n\n') + '\n',
    instructions: Object.fromEntries(sections.filter(section => section.instruction.trim()).map(section => [section.title.trim(), section.instruction])),
  }
}
