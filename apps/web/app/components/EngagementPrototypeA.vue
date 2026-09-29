<script setup lang="ts">
interface Assignment { company: string, initials: string, site: string, template: string, revision: number, updated: string, progress: number, migration: boolean, tone: string }
const props = defineProps<{ assignments: Assignment[] }>()
const search = ref('')
const filtered = computed(() => props.assignments.filter(item => `${item.company} ${item.site}`.toLocaleLowerCase('it').includes(search.value.toLocaleLowerCase('it'))))
const columns = [
  { accessorKey: 'company', header: 'Azienda' },
  { accessorKey: 'site', header: 'Sede' },
  { accessorKey: 'template', header: 'Modello' },
  { accessorKey: 'migration', header: 'Stato' },
  { accessorKey: 'updated', header: 'Ultima modifica' },
]
</script>

<template>
  <PrototypeShell section="Incarichi">
    <template #actions><UButton icon="i-lucide-plus" label="Nuovo incarico" to="/incarichi?screen=create&variant=A" /></template>
    <section class="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <div class="flex flex-wrap items-center justify-between gap-4">
        <p class="text-muted">Apri un fascicolo o avvia un incarico per una nuova sede.</p>
        <UInput v-model="search" icon="i-lucide-search" placeholder="Cerca azienda o sede" aria-label="Cerca azienda o sede" />
      </div>
      <UTable :data="filtered" :columns="columns" empty="Nessun incarico corrisponde alla ricerca.">
        <template #company-cell="{ row }"><UButton variant="link" :label="row.original.company" to="/incarichi?screen=detail&variant=A" /></template>
        <template #template-cell="{ row }"><span>{{ row.original.template }}</span><p class="text-muted">Revisione {{ row.original.revision }}</p></template>
        <template #migration-cell="{ row }"><UBadge :color="row.original.migration ? 'warning' : 'neutral'" variant="subtle">{{ row.original.migration ? 'Migrazione da valutare' : 'Corrente' }}</UBadge></template>
      </UTable>
      <p class="text-sm text-muted">Prototipo con dati dimostrativi. Le azioni aprono anteprime locali.</p>
    </section>
  </PrototypeShell>
</template>
