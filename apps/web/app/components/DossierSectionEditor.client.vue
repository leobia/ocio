<script setup lang="ts">
import { TableKit } from '@tiptap/extension-table'
const props = defineProps<{ modelValue: string, title: string, disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
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
  <UEditor v-else ref="visualEditor" v-slot="{ editor }" :model-value="modelValue" content-type="markdown" :extensions="extensions" :editable="!disabled" :mention="false" :starter-kit="{ heading: { levels: [3, 4, 5, 6] }, underline: false }" :editor-props="{ attributes: { role: 'textbox', 'aria-label': `Testo: ${title}`, 'aria-multiline': 'true', spellcheck: 'true' } }" placeholder="Scrivi il contenuto della sezione…" class="dossier-editor" @update:model-value="emit('update:modelValue', String($event))">
    <div role="toolbar" aria-label="Formattazione" class="mb-6 flex flex-wrap gap-1 border-b border-default pb-3">
      <UButton label="Grassetto" color="neutral" :variant="editor.isActive('bold') ? 'soft' : 'ghost'" :aria-pressed="editor.isActive('bold')" :disabled="disabled" @click="editor.chain().focus().toggleBold().run()" />
      <UButton label="Corsivo" color="neutral" :variant="editor.isActive('italic') ? 'soft' : 'ghost'" :aria-pressed="editor.isActive('italic')" :disabled="disabled" @click="editor.chain().focus().toggleItalic().run()" />
      <UButton label="Sottotitolo" color="neutral" :variant="editor.isActive('heading', { level: 3 }) ? 'soft' : 'ghost'" :disabled="disabled" @click="editor.chain().focus().toggleHeading({ level: 3 }).run()" />
      <UButton label="Elenco" color="neutral" variant="ghost" :disabled="disabled" @click="editor.chain().focus().toggleBulletList().run()" />
      <UButton label="Elenco numerato" color="neutral" variant="ghost" :disabled="disabled" @click="editor.chain().focus().toggleOrderedList().run()" />
      <UButton label="Tabella" color="neutral" variant="ghost" :disabled="disabled || editor.isActive('table')" @click="editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()" />
      <template v-if="editor.isActive('table')">
        <UButton label="Aggiungi riga" color="neutral" variant="ghost" :disabled="disabled" @click="editor.chain().focus().addRowAfter().run()" />
        <UButton label="Aggiungi colonna" color="neutral" variant="ghost" :disabled="disabled" @click="editor.chain().focus().addColumnAfter().run()" />
        <UButton label="Elimina riga" color="neutral" variant="ghost" :disabled="disabled" @click="editor.chain().focus().deleteRow().run()" />
        <UButton label="Elimina colonna" color="neutral" variant="ghost" :disabled="disabled" @click="editor.chain().focus().deleteColumn().run()" />
        <UButton label="Elimina tabella" color="neutral" variant="ghost" :disabled="disabled" @click="editor.chain().focus().deleteTable().run()" />
      </template>
      <UButton label="Annulla" color="neutral" variant="ghost" :disabled="disabled || !editor.can().undo()" @click="editor.chain().focus().undo().run()" />
      <UButton label="Ripeti" color="neutral" variant="ghost" :disabled="disabled || !editor.can().redo()" @click="editor.chain().focus().redo().run()" />
    </div>
  </UEditor>
</template>

<style scoped>
.dossier-editor :deep(.tiptap){min-height:420px;font-family:Georgia,serif;font-size:17px;line-height:1.85;outline:none;overflow-wrap:anywhere}
.dossier-editor :deep(.tiptap:focus-visible){outline:2px solid var(--ui-primary);outline-offset:8px}
.dossier-editor :deep(p){margin:0 0 1em}.dossier-editor :deep(h3),.dossier-editor :deep(h4){font-weight:600;font-size:1.25em;margin:1.5em 0 .75em}
.dossier-editor :deep(ul){list-style:disc;padding-left:1.5em}.dossier-editor :deep(ol){list-style:decimal;padding-left:1.5em}
.dossier-editor :deep(table){width:100%;table-layout:fixed;border-collapse:collapse;margin:1em 0}.dossier-editor :deep(td),.dossier-editor :deep(th){border:1px solid var(--ui-border);padding:8px;vertical-align:top;min-width:40px;position:relative}.dossier-editor :deep(th){background:var(--ui-bg-muted);font-weight:600}.dossier-editor :deep(.selectedCell){background:var(--ui-bg-accented)}
.dossier-editor :deep(pre){overflow:auto;white-space:pre;font-size:13px}.dossier-editor :deep(img){max-width:100%}
@media(max-width:640px){.dossier-editor :deep(.tiptap){font-size:16px}}
</style>
