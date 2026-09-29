<script setup lang="ts">
import type { DossierTemplate } from '~/types'
useHead({ title: 'Nuovo incarico — OCIO', htmlAttrs: { lang: 'it' } })
const api = useOcioApi()
const router = useRouter()
const templates = ref<DossierTemplate[]>([])
const company = ref('')
const site = ref('')
const referenceDate = ref(new Date().toLocaleDateString('en-CA'))
const revisionId = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const created = ref(false)
const options = computed(() => templates.value.flatMap(template => [...template.revisions].reverse().map(revision => ({ label: `${template.name} · revisione ${revision.number}`, value: revision.id }))))
const valid = computed(() => company.value.trim() && site.value.trim() && referenceDate.value && options.value.some(item => item.value === revisionId.value))
useUnsavedChanges(computed(() => !created.value && Boolean(company.value || site.value)))
async function load() {
  loading.value = true
  error.value = ''
  try {
    templates.value = await api.listTemplates()
    const template = templates.value.find(item => item.is_default) || templates.value[0]
    revisionId.value = template?.revisions.at(-1)?.id || ''
  }
  catch (reason) { error.value = (reason as Error).message }
  finally { loading.value = false }
}
async function create() {
  if (!valid.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    const engagement = await api.createEngagement({ company: company.value.trim(), site: site.value.trim(), reference_date: referenceDate.value, template_revision_id: revisionId.value })
    created.value = true
    await router.push(`/incarichi/${engagement.id}`)
  }
  catch (reason) { error.value = (reason as Error).message }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <AppShell section="Nuovo incarico" back>
    <form class="mx-auto grid max-w-5xl items-start gap-6 p-4 sm:p-6 lg:grid-cols-2" @submit.prevent="create">
      <UAlert v-if="error" class="lg:col-span-2" role="alert" color="error" :title="error" />
      <p v-if="loading" role="status">Caricamento modelli…</p>
      <template v-else>
        <UCard>
          <template #header><h2 class="font-semibold">Dati dell’incarico</h2></template>
          <fieldset :disabled="saving" class="space-y-4">
            <UFormField label="Azienda" required><UInput v-model="company" required maxlength="300" class="w-full" /></UFormField>
            <UFormField label="Sede" required><UInput v-model="site" required maxlength="300" class="w-full" /></UFormField>
            <UFormField label="Data di riferimento" required><UInput v-model="referenceDate" required type="date" class="w-full" /></UFormField>
            <UFormField label="Modello e revisione" required><USelect v-model="revisionId" :items="options" placeholder="Scegli il modello" class="w-full" /></UFormField>
            <div v-if="!options.length" class="space-y-2"><p class="text-sm text-muted">Nessun modello disponibile.</p><UButton color="neutral" variant="outline" @click="load">Ricarica modelli</UButton></div>
            <UButton to="/modelli" variant="link">Gestisci modelli</UButton>
          </fieldset>
        </UCard>
        <UCard>
          <template #header><h2 class="font-semibold">Riepilogo</h2></template>
          <dl class="space-y-4"><div v-for="(value, label) in { Azienda: company, Sede: site, Data: referenceDate, Modello: options.find(item => item.value === revisionId)?.label }" :key="label"><dt class="text-sm text-muted">{{ label }}</dt><dd class="break-words">{{ value || '—' }}</dd></div></dl>
          <template #footer><UButton type="submit" :loading="saving" :disabled="!valid || saving">Crea incarico</UButton></template>
        </UCard>
      </template>
    </form>
  </AppShell>
</template>
