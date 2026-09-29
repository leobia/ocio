<script setup lang="ts">
import type { Editor } from '@tiptap/vue-3'
import type { EditorToolbarItem } from '@nuxt/ui'
import { TableKit } from '@tiptap/extension-table'
const props = defineProps<{ modelValue: string, title: string, disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
// Keep the editor's own Markdown during typing: section separators belong to the
// dossier, and feeding them back to Tiptap resets content and undo history.
const editorValue = ref(props.modelValue)
watch(() => props.modelValue, value => {
  if (value.trimEnd() !== editorValue.value.trimEnd()) editorValue.value = value
})
function update(value: string | object) {
  editorValue.value = String(value)
  emit('update:modelValue', editorValue.value)
}
const toolbarItems: EditorToolbarItem[][] = [
  [
    { kind: 'undo', icon: 'i-lucide-undo', 'aria-label': 'Annulla', tooltip: { text: 'Annulla' } },
    { kind: 'redo', icon: 'i-lucide-redo', 'aria-label': 'Ripeti', tooltip: { text: 'Ripeti' } },
  ],
  [
    { kind: 'heading', level: 3, icon: 'i-lucide-heading-3', 'aria-label': 'Sottotitolo', tooltip: { text: 'Sottotitolo' } },
    { kind: 'mark', mark: 'bold', icon: 'i-lucide-bold', 'aria-label': 'Grassetto', tooltip: { text: 'Grassetto' } },
    { kind: 'mark', mark: 'italic', icon: 'i-lucide-italic', 'aria-label': 'Corsivo', tooltip: { text: 'Corsivo' } },
  ],
  [
    { kind: 'bulletList', icon: 'i-lucide-list', 'aria-label': 'Elenco', tooltip: { text: 'Elenco' } },
    { kind: 'orderedList', icon: 'i-lucide-list-ordered', 'aria-label': 'Elenco numerato', tooltip: { text: 'Elenco numerato' } },
  ],
]
function tableItems(editor: Editor): EditorToolbarItem[] {
  return [{
    icon: 'i-lucide-table', 'aria-label': 'Tabella', tooltip: { text: 'Tabella' },
    items: [
      { label: 'Inserisci tabella', disabled: editor.isActive('table'), onSelect: () => { editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run() } },
      ...editor.isActive('table') ? [
        { label: 'Aggiungi riga', onSelect: () => { editor.chain().focus().addRowAfter().run() } },
        { label: 'Aggiungi colonna', onSelect: () => { editor.chain().focus().addColumnAfter().run() } },
        { label: 'Elimina riga', onSelect: () => { editor.chain().focus().deleteRow().run() } },
        { label: 'Elimina colonna', onSelect: () => { editor.chain().focus().deleteColumn().run() } },
        { label: 'Elimina tabella', onSelect: () => { editor.chain().focus().deleteTable().run() } },
      ] : [],
    ],
  }]
}
const extensions = [TableKit]
const visualEditor = useTemplateRef('visualEditor')
watch([() => props.disabled, () => visualEditor.value?.editor], ([disabled, editor]) => {
  editor?.setEditable(!disabled, false)
})
// These constructs do not round-trip through the visual editor. Keep their original Markdown editable.
const sourceOnly = computed(() => /(^ {0,3}<[A-Za-z!/]|^ {0,3}\[[^\]]+\]:|\[\^[^\]]+\]|^#{1,2} )/m.test(props.modelValue))
</script>

<template>
  <UFormField v-if="sourceOnly" :label="`Testo: ${title}`" description="Questa sezione include formattazione da conservare in Markdown.">
    <UTextarea :model-value="modelValue" :disabled="disabled" :rows="22" class="w-full font-mono" @update:model-value="emit('update:modelValue', $event)" />
  </UFormField>
  <UEditor v-else ref="visualEditor" v-slot="{ editor }" :model-value="editorValue" content-type="markdown" :extensions="extensions" :editable="!disabled" :mention="false" :starter-kit="{ heading: { levels: [3, 4, 5, 6] }, underline: false }" :editor-props="{ attributes: { role: 'textbox', 'aria-label': `Testo: ${title}`, 'aria-multiline': 'true', spellcheck: 'true' } }" placeholder="Scrivi il contenuto della sezione…" class="dossier-editor" @update:model-value="update">
    <div class="mb-4 flex flex-wrap items-center gap-1 border-b border-default pb-2">
      <UEditorToolbar :editor="editor" :items="toolbarItems" aria-label="Formattazione" />
      <UEditorToolbar :editor="editor" :items="tableItems(editor)" aria-label="Gestione tabella" />
    </div>
  </UEditor>
</template>

<style scoped>
.dossier-editor :deep(.tiptap){min-height:420px;overflow-wrap:anywhere}
.dossier-editor :deep(table){width:100%;table-layout:fixed;border-collapse:collapse;margin:1em 0}.dossier-editor :deep(td),.dossier-editor :deep(th){border:1px solid var(--ui-border);padding:8px;vertical-align:top;min-width:40px;position:relative}.dossier-editor :deep(th){background:var(--ui-bg-muted);font-weight:600}.dossier-editor :deep(.selectedCell){background:var(--ui-bg-accented)}
.dossier-editor :deep(pre){overflow:auto;white-space:pre;font-size:13px}.dossier-editor :deep(img){max-width:100%}

</style>
