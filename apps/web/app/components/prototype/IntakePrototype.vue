<script setup lang="ts">
// THROWAWAY #25: three intake layouts on the existing dossier route (?variant=A|B|C).
const route = useRoute()
const router = useRouter()
const variants = ['A', 'B', 'C']
const variant = computed(() => variants.includes(String(route.query.variant)) ? String(route.query.variant) : 'A')
const names: Record<string, string> = { A: 'Percorso guidato', B: 'Dagli appunti ai dati', C: 'Prima il sopralluogo' }
type Status = 'Confermato' | 'Proposto' | 'Sconosciuto' | 'Da verificare'
interface Field { id: string, group: string, label: string, value: string, status: Status, source: string }
const groups = ['Azienda e sedi', 'Organizzazione della sicurezza', 'Lavoratori e mansioni', 'Attività', 'Ambienti', 'Attrezzature', 'Emergenze', 'Formazione', 'Sorveglianza sanitaria', 'Appalti']
const fields = ref<Field[]>(groups.map((group, index) => ({
  id: String(index), group,
  label: ['Sedi operative', 'Referente della sicurezza', 'Numero di lavoratori', 'Attività svolte', 'Ambienti da visitare', 'Attrezzature utilizzate', 'Addetti alle emergenze', 'Attestati disponibili', 'Informazioni da raccogliere', 'Sono presenti imprese esterne?'][index]!,
  value: index === 0 ? 'Sede di esempio · Padova' : '', status: index === 0 ? 'Confermato' : 'Sconosciuto',
  source: index === 0 ? 'Inserimento manuale · esempio' : 'Non ancora raccolto',
})))
fields.value.push({ id: 'contractors', group: 'Appalti', label: 'Quali attività svolgono le imprese esterne?', value: '', status: 'Sconosciuto', source: 'Non ancora raccolto' })
const activeGroup = ref('Appalti')
const selected = ref<string[]>([])
const exampleNotes = 'Sono circa 18 lavoratori. Si eseguono assemblaggi meccanici. Le pulizie sono affidate a una ditta esterna.'
const notes = ref(exampleNotes)
const notice = ref('')
const showCollection = ref(false)
const pending = computed(() => fields.value.filter(f => f.status === 'Proposto' || f.status === 'Da verificare'))
const applicable = computed(() => fields.value.filter(f => f.id !== 'contractors' || fields.value.find(x => x.id === '9')?.value === 'Sì'))
const visibleFields = computed(() => applicable.value.filter(f => f.group === activeGroup.value))
const confirmed = computed(() => applicable.value.filter(f => f.status === 'Confermato').length)
function extract() {
  if (notes.value !== exampleNotes) { notice.value = 'La demo simula soltanto gli appunti di esempio. Ripristinali per provare la revisione.'; return }
  for (const [id, value, source] of [['2', '18', 'Sono circa 18 lavoratori.'], ['3', 'Assemblaggi meccanici', 'Si eseguono assemblaggi meccanici.'], ['9', 'Sì', 'Le pulizie sono affidate a una ditta esterna.'], ['contractors', 'Pulizie', 'Le pulizie sono affidate a una ditta esterna.']]) {
    const field = fields.value.find(f => f.id === id)!
    if (field.status === 'Confermato') continue
    Object.assign(field, { value, status: 'Proposto', source })
  }
  notice.value = 'Proposte simulate pronte. Nessun dato è stato confermato automaticamente.'
}
function approve() {
  fields.value.filter(f => selected.value.includes(f.id) && (f.status === 'Proposto' || f.status === 'Da verificare')).forEach(f => { f.status = 'Confermato' })
  selected.value = []
  notice.value = 'Selezione confermata nella demo.'
}
function edit(field: Field) { field.status = 'Da verificare' }
interface Item { id: string, text: string, origin: string, state: string }
const checklist = ref<Item[]>([])
function generate() {
  for (const field of applicable.value.filter(f => f.status !== 'Confermato')) {
    if (!checklist.value.some(item => item.id === field.id)) checklist.value.push({ id: field.id, text: `Verificare: ${field.label.toLowerCase()}`, origin: `${field.group} · dato ${field.status.toLowerCase()}`, state: 'Da fare' })
  }
  notice.value = 'Checklist aggiornata dalle lacune dimostrative. Le voci già modificate sono conservate.'
}
function addItem() { checklist.value.push({ id: `manual-${Date.now()}`, text: 'Nuova verifica', origin: 'Aggiunta dall’operatore', state: 'Da fare' }) }
function cycle(direction: number) { router.replace({ query: { ...route.query, variant: variants[(variants.indexOf(variant.value) + direction + 3) % 3] } }) }
function keyboard(event: KeyboardEvent) {
  if ((event.target as HTMLElement).closest('input, textarea, select, button, [contenteditable]')) return
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); cycle(event.key === 'ArrowRight' ? 1 : -1) }
}
onMounted(() => { generate(); notice.value = ''; window.addEventListener('keydown', keyboard) })
onUnmounted(() => window.removeEventListener('keydown', keyboard))
</script>

<template>
  <div class="intake-prototype" :class="`variant-${variant}`">
    <div class="demo-note"><strong>PROTOTIPO #25</strong> · Azienda fittizia · modifiche solo in memoria · estrazione simulata</div>
    <header class="intro">
      <div><p class="eyebrow">OFFICINA ESEMPIO / SEDE DI PADOVA</p><h2>{{ names[variant] }}</h2><p>Dal primo colloquio alla visita in azienda.</p></div>
      <div class="progress"><strong>{{ confirmed }} / {{ applicable.length }}</strong><span>dati confermati</span></div>
    </header>
    <p v-if="notice" role="status" class="notice">{{ notice }}</p>
    <div class="workspace">
      <nav v-if="variant === 'A'" class="steps" aria-label="Ambiti della raccolta">
        <p class="eyebrow">01 / RACCOLTA GUIDATA</p>
        <button v-for="(group, i) in groups" :key="group" :class="{ active: activeGroup === group }" @click="activeGroup = group"><span>{{ String(i + 1).padStart(2, '0') }}</span>{{ group }}</button>
      </nav>
      <section v-if="variant !== 'C' || showCollection" class="panel collection">
        <div class="panel-title"><div><p class="eyebrow">DATI DEL CASO</p><h3>{{ activeGroup }}</h3></div><span class="tag">Manuale</span></div>
        <label v-if="variant !== 'A'" class="field">Ambito<select v-model="activeGroup"><option v-for="group in groups" :key="group">{{ group }}</option></select></label>
        <p class="muted">Compila ciò che sai. Puoi lasciare le informazioni sconosciute.</p>
        <div v-for="field in visibleFields" :key="field.id" class="field-box">
          <label class="field">{{ field.label }}
            <select v-if="field.id === '9'" v-model="field.value" @change="edit(field)"><option value="">Non lo so</option><option>Sì</option><option>No</option></select>
            <input v-else v-model="field.value" placeholder="Informazione non ancora raccolta" @input="edit(field)">
          </label>
          <div class="row"><span class="tag" :data-status="field.status">{{ field.status }}</span><button class="text-button" :disabled="!field.value || field.status === 'Confermato'" @click="field.status = 'Confermato'; field.source = field.source === 'Non ancora raccolto' ? 'Compilazione manuale · demo' : field.source">Conferma dato</button></div>
          <small>{{ field.source }}</small>
        </div>
        <p v-if="activeGroup === 'Appalti'" class="hint">Il dettaglio sulle attività compare solo scegliendo “Sì”.</p>
        <button v-if="variant === 'A'" class="primary" @click="activeGroup = groups[(groups.indexOf(activeGroup) + 1) % groups.length]!">Prossimo ambito →</button>
      </section>
      <section class="panel notes">
        <div class="panel-title"><div><p class="eyebrow">{{ variant === 'B' ? '01 / PUNTO DI PARTENZA' : 'APPUNTI DEL COLLOQUIO' }}</p><h3>Le parole dell’azienda</h3></div></div>
        <label class="field">Appunti<textarea v-model="notes" rows="6" /></label>
        <p class="muted">L’estrazione propone valori da rivedere insieme al passaggio originale.</p>
        <div class="row"><button class="primary" @click="extract">Simula estrazione</button><button class="text-button" @click="notes = exampleNotes">Ripristina esempio</button></div>
      </section>
      <section class="panel review">
        <div class="panel-title"><div><p class="eyebrow">{{ variant === 'B' ? '02 / REVISIONE' : 'DA RIVEDERE' }}</p><h3>Proposte e verifiche</h3></div><span class="tag">{{ pending.length }}</span></div>
        <div v-if="!pending.length" class="empty">Nessuna proposta in attesa.<br>Prova l’estrazione dagli appunti di esempio.</div>
        <article v-for="field in pending" :key="field.id" class="proposal">
          <label class="row"><input v-model="selected" type="checkbox" :value="field.id"><strong>{{ field.label }}</strong></label>
          <input v-model="field.value" :aria-label="`Correggi: ${field.label}`" @input="edit(field)">
          <blockquote>«{{ field.source }}»</blockquote>
          <div class="row"><span class="tag" :data-status="field.status">{{ field.status }}</span><button class="text-button" @click="field.status = 'Da verificare'; selected = selected.filter(id => id !== field.id)">Da verificare</button></div>
        </article>
        <button class="primary" :disabled="!selected.length" @click="approve">Conferma selezionati ({{ selected.length }})</button>
      </section>
      <section class="panel checklist">
        <div class="panel-title"><div><p class="eyebrow">{{ variant === 'C' ? 'IL PROSSIMO PASSO' : 'PRIMO SOPRALLUOGO' }}</p><h3>Da portare in visita</h3></div><span class="tag">{{ checklist.filter(i => i.state === 'Completata').length }}/{{ checklist.length }}</span></div>
        <p class="muted">Una traccia modificabile dalle lacune del caso. Le sezioni sono dimostrative, da validare con l’RSPP.</p>
        <div class="row"><button class="primary" @click="generate">Aggiorna dalle lacune</button><button class="text-button" @click="addItem">+ Aggiungi voce</button><button v-if="variant === 'C'" class="text-button" @click="showCollection = !showCollection">{{ showCollection ? 'Chiudi dati' : 'Completa i dati' }}</button></div>
        <div class="checklist-items"><article v-for="item in checklist" :key="item.id" class="check-item">
          <input v-model="item.text" aria-label="Voce checklist">
          <select v-model="item.state" aria-label="Stato voce"><option>Da fare</option><option>Completata</option><option>Da verificare</option></select>
          <small>Origine: {{ item.origin }}</small>
        </article></div>
      </section>
    </div>
    <details class="state"><summary>Stato della demo · {{ names[variant] }} · {{ confirmed }} confermati · {{ pending.length }} da rivedere</summary><pre>{{ JSON.stringify({ fields, checklist }, null, 2) }}</pre></details>
    <nav class="switcher" aria-label="Varianti prototipo"><button aria-label="Variante precedente" @click="cycle(-1)">←</button><div><small>PROTOTIPO · {{ variant }} / C</small><strong>{{ names[variant] }}</strong></div><button aria-label="Variante successiva" @click="cycle(1)">→</button></nav>
  </div>
</template>

<style scoped>
.intake-prototype{padding:24px 28px 110px;--line:#dbe3dd;--ink:#203e32;color:var(--ink);background:#f6f8f5;min-height:calc(100vh - 64px)}
.demo-note{font-size:12px;color:#65736a;border-bottom:1px solid var(--line);padding-bottom:12px}.demo-note strong{color:#376849}.intro{display:flex;justify-content:space-between;gap:24px;align-items:center;padding:28px 0}.eyebrow{font-size:10px;letter-spacing:.12em;font-weight:700;color:#64796a;margin-bottom:9px}h2{font-size:30px;line-height:1.2;font-weight:650;margin-bottom:8px}h3{font-size:20px;font-weight:600}.intro p:not(.eyebrow),.muted{color:#66756c;font-size:14px}.progress{display:flex;flex-direction:column;min-width:110px}.progress strong{font-size:26px}.progress span{font-size:12px}.workspace{display:grid;gap:20px;align-items:start}.panel{padding:24px;background:white;border:1px solid var(--line);border-radius:14px;min-width:0}.panel-title{display:flex;justify-content:space-between;align-items:start;gap:12px;margin-bottom:20px}.panel-title .eyebrow{margin-bottom:5px}.variant-A .workspace{grid-template-columns:210px minmax(0,1fr) minmax(260px,.8fr)}.variant-A .steps{grid-column:1;grid-row:1 / 4}.variant-A .collection{grid-column:2;grid-row:1 / 3}.variant-A .notes{grid-column:3;grid-row:1}.variant-A .review{grid-column:3;grid-row:2}.variant-A .checklist{grid-column:2 / 4}.steps button{display:flex;text-align:left;gap:12px;width:100%;padding:12px 10px;border-radius:8px;font-size:13px}.steps button span{font-size:11px;opacity:.5}.steps button.active{background:#dfede2;color:#245e3c;font-weight:650}.variant-B .workspace{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.variant-B .notes{grid-column:1;grid-row:1}.variant-B .review{grid-column:2;grid-row:1 / 3}.variant-B .collection{grid-column:1;grid-row:2}.variant-B .checklist{grid-column:1 / 3}.variant-C .workspace{grid-template-columns:minmax(0,1.6fr) minmax(280px,1fr)}.variant-C .checklist{grid-column:1;grid-row:1 / 4}.variant-C .notes,.variant-C .review,.variant-C .collection{grid-column:2}.variant-C .collection{grid-row:1}.field{display:grid;gap:8px;font-size:14px;font-weight:550;margin-bottom:14px}input:not([type=checkbox]),textarea,select{width:100%;border:1px solid #cbd8cf;border-radius:7px;padding:10px 12px;background:white;color:#203e32;font:inherit;font-size:14px;min-width:0}textarea{resize:vertical}input[type=checkbox]{accent-color:#2e6750;width:17px;height:17px;flex-shrink:0}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}.field-box{padding:20px 0;border-bottom:1px solid var(--line);margin-bottom:18px}.field-box small,.check-item small{display:block;margin-top:8px;color:#6d7a71;font-size:11px}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.tag{display:inline-block;padding:4px 8px;border-radius:5px;font-size:11px;background:#eef1ed;white-space:nowrap}.tag[data-status=Confermato]{background:#dff1e5;color:#25633b}.tag[data-status=Proposto]{background:#e7edff;color:#43578a}.tag[data-status='Da verificare']{background:#fff0d5;color:#886024}.primary{padding:10px 14px;border-radius:7px;background:#2e6750;color:white;font-size:13px;font-weight:600}.text-button{font-size:12px;color:#2e6750;text-decoration:underline;text-underline-offset:3px;padding:5px 0}.hint{font-size:12px;color:#6d7a71;margin:16px 0}.muted{margin-bottom:18px}.proposal{border-top:1px solid var(--line);padding:16px 0}.proposal>.row:first-child{font-size:13px;margin-bottom:10px}blockquote{font-size:12px;border-left:2px solid #c4d5c8;padding-left:10px;color:#66756c;margin:12px 0}.empty{padding:25px 0 35px;font-size:14px;color:#79857d;line-height:1.7}.checklist-items{margin-top:20px;display:grid;gap:10px}.check-item{display:grid;grid-template-columns:minmax(0,1fr) 140px;gap:5px 10px;border-top:1px solid var(--line);padding-top:12px}.check-item small{grid-column:1 / -1}.notice{background:#e4efe6;padding:12px;border-radius:7px;margin-bottom:20px;font-size:13px}.state{margin-top:24px;font-size:12px;color:#64796a}.state pre{overflow:auto;max-height:260px;margin-top:12px}.switcher{position:fixed;z-index:50;bottom:20px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:20px;background:#172e24;color:white;border:1px solid #718579;padding:10px 16px;border-radius:50px;box-shadow:0 8px 30px #10231930;max-width:calc(100vw - 24px);white-space:nowrap}.switcher div{display:flex;flex-direction:column;text-align:center}.switcher small{font-size:9px;letter-spacing:.1em;color:#acc4b4}.switcher strong{font-size:12px}.switcher button{padding:8px;font-size:20px}
@media(max-width:1100px){.variant-A .workspace{grid-template-columns:170px minmax(0,1fr)}.variant-A .collection,.variant-A .notes,.variant-A .review,.variant-A .checklist{grid-column:2;grid-row:auto}.variant-A .steps{grid-row:1 / 5}}
@media(max-width:700px){.intake-prototype{padding:18px 16px 110px}.intro{gap:12px}h2{font-size:25px}.progress{min-width:70px}.progress strong{font-size:22px}.panel{padding:18px}.workspace{display:flex!important;flex-direction:column}.workspace>*{width:100%}.steps{display:flex;overflow:auto;gap:5px}.steps>.eyebrow{display:none}.steps button{min-width:150px}.variant-B .notes,.variant-C .checklist{order:-1}.check-item{grid-template-columns:minmax(0,1fr)}.check-item small{grid-column:1}.check-item select{width:auto}.demo-note{line-height:1.6}}
</style>
