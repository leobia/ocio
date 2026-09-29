<script setup lang="ts">
import type { EngagementSummary } from '~/types'
useHead({ title: 'Incarichi — OCIO', htmlAttrs: { lang: 'it' } })
const api = useOcioApi()
const assignments = ref<EngagementSummary[]>([])
const search = ref('')
const loading = ref(true)
const error = ref('')
const filtered = computed(() => assignments.value.filter(item => `${item.company} ${item.site}`.toLocaleLowerCase('it').includes(search.value.toLocaleLowerCase('it'))))
const columns = [
  { accessorKey: 'company', header: 'Azienda' },
  { accessorKey: 'site', header: 'Sede' },
  { accessorKey: 'template_name', header: 'Modello' },
  { accessorKey: 'has_pending_migration', header: 'Stato' },
  { accessorKey: 'reference_date', header: 'Riferimento' },
]
async function load() {
  loading.value = true
  error.value = ''
  try { assignments.value = await api.listEngagements() }
  catch (reason) { error.value = (reason as Error).message }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <AppShell section="Incarichi">
    <template #actions><UButton icon="i-lucide-plus" label="Nuovo incarico" to="/incarichi/nuovo" /></template>
    <section class="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <div class="flex flex-wrap items-center justify-between gap-4">
        <p class="text-muted">Crea un incarico oppure aprine uno esistente.</p>
        <UInput v-model="search" icon="i-lucide-search" placeholder="Cerca azienda o sede" aria-label="Cerca azienda o sede" />
      </div>
      <UAlert v-if="error" role="alert" color="error" :title="error" :actions="[{ label: 'Riprova', onClick: load }]" />
      <UTable v-else :loading="loading" :data="filtered" :columns="columns" :empty="search ? 'Nessun incarico corrisponde alla ricerca.' : 'Nessun incarico. Crea il primo per iniziare.'">
        <template #company-cell="{ row }"><UButton variant="link" :label="row.original.company" :to="`/incarichi/${row.original.id}`" /></template>
        <template #template_name-cell="{ row }"><span>{{ row.original.template_name }}</span><p class="text-muted">Revisione {{ row.original.template_revision }}</p></template>
        <template #has_pending_migration-cell="{ row }"><UBadge :color="row.original.has_pending_migration ? 'warning' : 'neutral'" variant="subtle">{{ row.original.has_pending_migration ? 'Migrazione da valutare' : 'Corrente' }}</UBadge></template>
      </UTable>
    </section>
  </AppShell>
</template>
