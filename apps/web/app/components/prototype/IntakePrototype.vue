<script setup lang="ts">
// THROWAWAY #25: revision of selected layout A. Document sections, editable prose and source material.
// Previous A/B/C variants are archived on prototype/issue-25-intake-v1.
interface Section { title: string, text: string, sources: string[] }
const sections = ref<Section[]>([
  { title: 'Azienda e sede', text: '', sources: [] },
  { title: 'Attività e organizzazione del lavoro', text: `L’azienda svolge attività di assemblaggio di componenti meccanici. Il lavoro si articola nella ricezione dei materiali, nella preparazione dei componenti e nell’assemblaggio al banco. I prodotti assemblati vengono successivamente imballati e trasferiti nell’area destinata alla spedizione.

Secondo quanto riferito durante il sopralluogo, in officina lavorano circa diciotto persone. Non è stato acquisito un elenco aggiornato del personale; la distribuzione dei lavoratori fra le diverse mansioni resta quindi da precisare.

Le attività si svolgono in un unico turno diurno. Nella visita sono state osservate le postazioni di assemblaggio e l’area di ricezione dei materiali. La descrizione delle operazioni meno frequenti dovrà essere integrata con le informazioni del referente aziendale.

Le pulizie sono affidate a un’impresa esterna. Gli appunti non riportano frequenza, orari di accesso o modalità di coordinamento.`, sources: ['notes'] },
  { title: 'Ambienti di lavoro', text: `Gli spazi visitati comprendono l’officina, l’area di deposito dei materiali e gli uffici. Nell’officina le postazioni di assemblaggio sono disposte lungo due file di banchi; il deposito si trova in prossimità dell’accesso utilizzato per le consegne.

Durante la visita erano presenti alcuni imballaggi nell’area di passaggio fra il deposito e i banchi. Gli appunti descrivono la situazione osservata in quel momento e non consentono di stabilire se si tratti di una condizione abituale.

Non sono state annotate le dimensioni dei locali né è stata acquisita una planimetria. Questi elementi non sono pertanto riportati nella presente descrizione.`, sources: ['notes'] },
  { title: 'Macchine e attrezzature', text: `Le operazioni di assemblaggio osservate vengono svolte ai banchi con utensili manuali e avvitatori. Il materiale raccolto non contiene un inventario completo delle attrezzature.

Per ciascuna attrezzatura, la descrizione potrà essere integrata con identificazione, impiego, modalità operative e documentazione disponibile. Non sono stati acquisiti manuali o registri di manutenzione.`, sources: ['notes'] },
  { title: 'Valutazione dei rischi', text: '', sources: [] },
  { title: 'Misure e procedure', text: '', sources: [] },
  { title: 'Emergenze', text: '', sources: [] },
  { title: 'Formazione', text: '', sources: [] },
  { title: 'Sorveglianza sanitaria', text: '', sources: [] },
  { title: 'Appalti', text: '', sources: [] },
])
const activeIndex = ref(1)
const current = computed(() => sections.value[activeIndex.value]!)
const company = ref('Officina esempio')
const site = ref('Padova · sede operativa')
const materialOpen = ref(false)
const notes = ref(`Assemblaggio componenti meccanici. Arrivo materiali, preparazione, montaggio ai banchi, imballaggio e spedizione. Circa 18 persone in officina, chiedere elenco aggiornato e mansioni. Un turno diurno.

Visitati officina, deposito e uffici. Due file di banchi. Deposito vicino all’ingresso consegne. Imballaggi nel passaggio fra deposito e banchi: non so se abituale. Non ho dimensioni né planimetria.

Utensili manuali e avvitatori ai banchi. Non ho elenco completo, manuali e registri manutenzione. Pulizie ditta esterna, orari da chiarire.`)
const notice = ref('')
const saved = ref(false)
interface Attachment { id: string, name: string, type: string, url: string }
const attachments = ref<Attachment[]>([])
const viewed = ref<Attachment | null>(null)
function selectSection(index: number) { activeIndex.value = index; notice.value = '' }
function updateText(event: Event) { current.value.text = (event.target as HTMLElement).innerText; saved.value = false }
function addFiles(event: Event) {
  const input = event.target as HTMLInputElement
  for (const file of Array.from(input.files || [])) attachments.value.push({ id: `${Date.now()}-${attachments.value.length}`, name: file.name, type: file.type, url: URL.createObjectURL(file) })
  input.value = ''
  notice.value = 'File aperti solo in questo browser. La demo non li carica sul server e non li analizza.'
}
function save() { saved.value = true; notice.value = 'Versione simulata. Ricaricando la pagina le modifiche si perdono.' }
onUnmounted(() => attachments.value.forEach(file => URL.revokeObjectURL(file.url)))
</script>

<template>
  <div class="document-prototype">
    <div class="prototype-note">Prototipo · contenuto fittizio · modifiche solo in memoria</div>
    <header class="document-header">
      <div><p class="company">{{ company }}</p><h2>Fascicolo di sicurezza</h2><p class="subtitle">{{ site }}</p></div>
      <div class="actions"><button class="secondary" :aria-expanded="materialOpen" @click="materialOpen = !materialOpen">{{ materialOpen ? 'Chiudi materiale' : 'Materiale del sopralluogo' }}</button><button class="primary" @click="save">Salva versione demo</button></div>
    </header>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <div class="document-layout" :class="{ 'with-material': materialOpen }">
      <nav class="section-index" aria-label="Sezioni del fascicolo">
        <h3>Sezioni</h3>
        <button v-for="(section, index) in sections" :key="section.title" :aria-current="activeIndex === index ? 'page' : undefined" @click="selectSection(index)"><span class="section-number">{{ String(index + 1).padStart(2, '0') }}</span><span>{{ section.title }}</span></button>
        <p class="index-note">Indice dimostrativo.<br>Nel prodotto seguirà il modello scelto per l’incarico.</p>
      </nav>
      <section class="document-area" :aria-label="current.title">
        <div class="editor-meta"><span>Sezione {{ activeIndex + 1 }} di {{ sections.length }}</span><span>{{ saved ? 'Salvataggio simulato' : 'Bozza' }}</span></div>
        <div class="paper">
          <h3>{{ current.title }}</h3>
          <template v-if="activeIndex === 0">
            <p class="intro">Dati essenziali dell’incarico.</p>
            <label class="field">Azienda<input v-model="company" @input="saved = false"></label>
            <label class="field">Sede<input v-model="site" @input="saved = false"></label>
          </template>
          <div v-else :key="activeIndex" class="prose-editor" contenteditable="plaintext-only" role="textbox" aria-multiline="true" :aria-label="`Testo: ${current.title}`" :data-placeholder="'Scrivi qui il contenuto della sezione…'" @input="saved = false" @blur="updateText">{{ current.text }}</div>
          <footer class="paper-footer"><button v-if="current.sources.length" class="source-link" @click="materialOpen = true; viewed = null">Materiale utilizzato: appunti del sopralluogo ↗</button><p v-else>Puoi scrivere direttamente nel fascicolo.</p></footer>
        </div>
        <p class="editor-note">{{ activeIndex === 0 ? 'I dati anagrafici restano campi brevi.' : 'Scrivi e correggi direttamente il testo. Nessuna conferma per singolo dato.' }}</p>
      </section>
      <aside v-if="materialOpen" class="material-panel" aria-label="Materiale del sopralluogo">
        <div class="material-title"><h3>Materiale del sopralluogo</h3><button class="close-button" aria-label="Chiudi materiale" @click="materialOpen = false">×</button></div>
        <label class="field">Appunti<textarea v-model="notes" rows="13" /></label>
        <p class="material-help">La bozza di esempio è già compilata. In questa demo modificare gli appunti non genera nuovo testo.</p>
        <div class="files-heading"><h4>Foto e documenti</h4><label class="add-files">Aggiungi<input type="file" multiple aria-label="Aggiungi foto e documenti" accept="image/*,.pdf,.doc,.docx,.txt" @change="addFiles"></label></div>
        <p v-if="!attachments.length" class="empty-material">Nessun file aggiunto.</p>
        <ul v-else class="attachment-list"><li v-for="file in attachments" :key="file.id"><button @click="viewed = file">{{ file.name }}</button></li></ul>
        <div v-if="viewed" class="file-preview"><h4>{{ viewed.name }}</h4><img v-if="viewed.type.startsWith('image/')" :src="viewed.url" :alt="viewed.name"><iframe v-else-if="viewed.type === 'application/pdf'" :src="viewed.url" :title="viewed.name" /><p v-else>Anteprima non disponibile per questo formato.</p></div>
        <p class="material-help">File solo in memoria nel browser, senza analisi automatica.</p>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.document-prototype{background:#f5f6f3;min-height:calc(100vh - 64px);padding:20px 28px 50px;color:#26392f}.prototype-note{font-size:11px;color:#758076;padding-bottom:14px;border-bottom:1px solid #dfe4dd}.document-header{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:28px 0}.company{font-size:13px;color:#647369;margin-bottom:6px}h2{font-size:26px;font-weight:650;letter-spacing:-.02em}.subtitle{font-size:13px;color:#647369;margin-top:5px}.actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}button{cursor:pointer}.primary,.secondary{font-size:12px;font-weight:550;padding:10px 13px;border-radius:6px}.primary{background:#2e6750;color:white;border:1px solid #2e6750}.secondary{background:white;border:1px solid #d3dbd2;color:#35513e}.document-layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:28px;align-items:start}.document-layout.with-material{grid-template-columns:190px minmax(0,1fr) 310px;gap:20px}.section-index{padding-top:8px}.section-index h3{font-size:12px;font-weight:650;margin:0 10px 18px}.section-index>button{display:flex;gap:12px;text-align:left;width:100%;padding:12px 10px;border-radius:6px;font-size:13px;line-height:1.5;margin:2px 0}.section-index>button[aria-current=page]{background:#e0ebe1;color:#255538;font-weight:600}.section-number{font-size:10px;color:#7d897e;padding-top:3px}.index-note{font-size:11px;line-height:1.6;color:#7d897e;margin:30px 10px}.document-area{min-width:0}.editor-meta{display:flex;justify-content:space-between;font-size:11px;color:#748074;margin:8px 0 12px}.paper{max-width:860px;margin:auto;background:#fff;border:1px solid #dfe4dd;box-shadow:0 3px 12px #23362404;min-height:690px;padding:46px 48px;display:flex;flex-direction:column}.paper h3{font-family:Georgia,serif;font-size:27px;line-height:1.3;margin-bottom:28px;color:#27382b}.prose-editor{font-family:Georgia,serif;font-size:17px;line-height:1.95;white-space:pre-wrap;overflow-wrap:anywhere;min-height:450px;outline:none}.prose-editor:focus{outline:1px solid #b7c9b8;outline-offset:10px}.prose-editor:empty:before{content:attr(data-placeholder);color:#92998f}.paper-footer{border-top:1px solid #ecefe9;padding-top:18px;margin-top:30px;color:#758073;font-size:11px}.source-link{text-align:left;color:#506d54;text-decoration:underline;text-underline-offset:3px}.editor-note{font-size:11px;color:#758073;padding:14px 0}.field{display:grid;gap:8px;font-size:12px;font-weight:550;margin-bottom:20px}.field input,.field textarea{border:1px solid #d2dcd1;border-radius:5px;background:white;color:#293d2f;padding:10px 12px;font-size:13px;font-weight:400;line-height:1.65;width:100%;min-width:0}.field textarea{resize:vertical}.intro{font-size:14px;color:#758073;margin-bottom:30px}.material-panel{background:#fff;padding:20px;border:1px solid #dfe4dd;border-radius:7px;min-width:0}.material-title{display:flex;justify-content:space-between;align-items:start;gap:10px;margin-bottom:24px}.material-title h3{font-size:14px;font-weight:650}.close-button{font-size:23px;line-height:1}.material-help,.empty-material{font-size:11px;line-height:1.7;color:#7d897e;margin:12px 0}.files-heading{display:flex;align-items:center;justify-content:space-between;border-top:1px solid #dfe4dd;padding-top:20px;margin-top:25px}.files-heading h4{font-size:12px;font-weight:650}.add-files{font-size:12px;color:#2e6750;text-decoration:underline;position:relative;cursor:pointer}.add-files input{position:absolute;inset:0;opacity:0;width:100%;cursor:pointer}.attachment-list{list-style:none;margin:12px 0}.attachment-list button{text-align:left;font-size:12px;overflow-wrap:anywhere;padding:8px 0;color:#2e6750}.file-preview h4{font-size:12px;overflow-wrap:anywhere;margin-bottom:12px}.file-preview img{width:100%;height:auto}.file-preview iframe{width:100%;height:350px;border:0}.file-preview p{font-size:12px}.notice{font-size:12px;background:#e4eee4;padding:12px;margin-bottom:20px;border-radius:5px}
@media(min-width:1350px){.document-layout:not(.with-material) .paper{padding:50px 64px}}@media(max-width:1200px){.document-layout.with-material{grid-template-columns:175px minmax(0,1fr)}.material-panel{grid-column:2}.paper{padding:32px}}@media(max-width:700px){.document-prototype{padding:15px 16px 35px}.document-header{align-items:start;flex-direction:column;gap:18px}.actions{justify-content:flex-start}.document-layout,.document-layout.with-material{display:flex;flex-direction:column;gap:18px}.section-index{width:100%;display:flex;overflow:auto;gap:6px;padding:0 0 8px}.section-index h3,.index-note{display:none}.section-index>button{min-width:165px;margin:0}.document-area,.material-panel{width:100%}.paper{padding:25px 22px;min-height:600px}.paper h3{font-size:25px}.prose-editor{font-size:16px;line-height:1.9}.material-panel{order:-1}.editor-note{line-height:1.7}}
</style>
