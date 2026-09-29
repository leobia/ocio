<script setup lang="ts">
interface Assignment { company: string, initials: string, site: string, template: string, revision: number, updated: string, progress: number, migration: boolean, tone: string }
defineProps<{ assignments: Assignment[] }>()
const search = ref('')
const router = useRouter()
</script>

<template>
  <div class="workspace-a">
    <aside class="sidebar-a">
      <a class="brand-a" href="/"><span>O</span><strong>OCIO</strong></a>
      <nav>
        <small>LAVORO</small>
        <a class="active" href="#"><UIcon name="i-lucide-briefcase-business" /> Incarichi</a>
        <a href="#"><UIcon name="i-lucide-files" /> Modelli</a>
        <small>STRUMENTI</small>
        <a href="/"><UIcon name="i-lucide-message-square-text" /> Assistente</a>
        <a href="#"><UIcon name="i-lucide-library" /> Fonti</a>
      </nav>
      <div class="environment"><i /><span><strong>Alpha interna</strong><small>Casi fittizi o redatti</small></span></div>
    </aside>

    <main>
      <header class="bar-a"><div><small>Fascicoli di sicurezza</small><h1>Incarichi</h1></div><UButton icon="i-lucide-plus" label="Nuovo incarico" /></header>
      <section class="content-a">
        <header class="list-heading"><div><h2>Incarichi</h2><p>{{ assignments.length }} incarichi attivi, 2 con una revisione del modello da valutare.</p></div><div><UInput v-model="search" icon="i-lucide-search" placeholder="Cerca azienda o sede" /><UButton color="neutral" variant="outline" icon="i-lucide-list-filter" label="Filtri" /></div></header>
        <div class="table-a">
          <div class="head-a"><span>Azienda</span><span>Sede</span><span>Modello</span><span>Stato</span><span>Ultima modifica</span><span /></div>
          <button v-for="item in assignments" :key="item.company" @click="router.push({ query: { screen: 'detail', variant: 'A' } })">
            <span class="company-a"><i :class="item.tone">{{ item.initials }}</i><strong>{{ item.company }}</strong></span>
            <span>{{ item.site }}</span>
            <span class="model-a">{{ item.template }}<small>Revisione {{ item.revision }}</small></span>
            <span><UBadge v-if="item.migration" color="warning" variant="subtle">Migrazione da valutare</UBadge><span v-else class="current-a"><i /> Corrente</span></span>
            <span>{{ item.updated }}</span><UIcon name="i-lucide-chevron-right" />
          </button>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.workspace-a{min-height:100vh;display:grid;grid-template-columns:224px 1fr;color:#1d2420;background:#f5f6f3;font-family:Inter,ui-sans-serif,system-ui}.sidebar-a{position:sticky;top:0;display:flex;height:100vh;flex-direction:column;padding:20px 14px;border-right:1px solid #d9ddd8;background:#ecefeb}.brand-a{display:flex;align-items:center;gap:10px;padding:0 8px 26px;color:inherit;text-decoration:none}.brand-a span{display:grid;place-items:center;width:32px;height:32px;border-radius:4px;color:#fff;background:#174f3b;font-family:Georgia,serif;font-size:18px}.brand-a strong{font-size:13px;letter-spacing:.14em}.sidebar-a nav{display:grid;gap:2px}.sidebar-a nav small{margin:19px 9px 6px;color:#838d87;font-size:8px;font-weight:700;letter-spacing:.12em}.sidebar-a nav a{display:flex;align-items:center;gap:9px;padding:9px;border-radius:4px;color:#5e6963;font-size:11px;text-decoration:none}.sidebar-a nav a.active,.sidebar-a nav a:hover{color:#174f3b;background:#fff}.environment{display:flex;align-items:center;gap:8px;margin-top:auto;padding:10px;border-top:1px solid #d5dad5}.environment>i{width:6px;height:6px;border-radius:50%;background:#4b8d6d}.environment>span{display:grid}.environment strong{font-size:9px}.environment small{color:#7f8983;font-size:7px}.workspace-a main{min-width:0}.bar-a{display:flex;align-items:center;justify-content:space-between;height:68px;padding:0 28px;border-bottom:1px solid #dde1dc;background:#fafbf9}.bar-a small{color:#758078;font-size:8px}.bar-a h1{margin:2px 0 0;font-family:Georgia,serif;font-size:19px;font-weight:500}.content-a{max-width:1280px;margin:0 auto;padding:32px}.list-heading{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:18px}.list-heading h2{margin:0;font-size:19px;font-weight:600}.list-heading p{margin:5px 0 0;color:#737d77;font-size:10px}.list-heading>div:last-child{display:flex;gap:7px}.table-a{overflow:hidden;border:1px solid #dce0db;border-radius:4px;background:white}.head-a,.table-a>button{display:grid;grid-template-columns:1.15fr 1.2fr 1.2fr 1fr .7fr 16px;align-items:center;gap:16px}.head-a{padding:9px 14px;border-bottom:1px solid #dce0db;color:#7d8781;background:#f0f2ef;font-size:7px;font-weight:700;letter-spacing:.09em;text-transform:uppercase}.table-a>button{width:100%;padding:13px 14px;border:0;border-bottom:1px solid #e7eae6;color:#48524c;text-align:left;background:#fff;font-size:9px;cursor:pointer}.table-a>button:last-child{border:0}.table-a>button:hover{background:#f7f8f6}.company-a{display:flex;align-items:center;gap:9px}.company-a i{display:grid;place-items:center;width:30px;height:30px;border-radius:3px;color:#fff;font-size:8px;font-style:normal}.company-a strong{color:#222b26;font-size:10px}.forest{background:#245f48}.clay{background:#9a6549}.ink{background:#4e5964}.olive{background:#727b46}.model-a{display:grid;color:#28332d}.model-a small{margin-top:2px;color:#7e8882;font-size:7px}.current-a{display:flex;align-items:center;gap:5px;color:#47705c;font-size:8px;font-weight:600}.current-a i{width:5px;height:5px;border-radius:50%;background:#4d8a6c}@media(max-width:900px){.workspace-a{grid-template-columns:64px 1fr}.sidebar-a{padding-inline:10px}.brand-a strong,.sidebar-a nav small,.sidebar-a nav a:not(.active),.environment span{display:none}.brand-a{padding-inline:5px}.sidebar-a nav a{justify-content:center}.head-a,.table-a>button{grid-template-columns:1.2fr 1.2fr 1fr auto}.head-a span:nth-child(3),.head-a span:nth-child(5),.table-a>button>.model-a,.table-a>button>span:nth-child(5){display:none}}@media(max-width:640px){.workspace-a{display:block}.sidebar-a{position:static;height:auto;flex-direction:row;align-items:center}.brand-a{padding:0}.sidebar-a nav{display:flex;margin-left:auto}.environment{display:none}.content-a{padding:20px 12px}.list-heading{align-items:start;flex-direction:column}.head-a{display:none}.table-a>button{grid-template-columns:1fr auto}.table-a>button>span:not(.company-a):not(:nth-child(4)){display:none}}
</style>
