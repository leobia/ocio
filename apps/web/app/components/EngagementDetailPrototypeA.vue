<script setup lang="ts">
const text = ref(`# Fascicolo sicurezza aziendale

## 1. Anagrafica e organizzazione

Officine Bianchi S.r.l. — Stabilimento nord, Torino.

- RSPP: incarico confermato
- RLS: documentazione acquisita
- Medico competente: nomina da verificare

## 2. Valutazione dei rischi

Il DVR generale è stato acquisito. La valutazione rumore richiede un aggiornamento relativo alla nuova linea produttiva.

## 3. Procedure operative

- Procedura manutenzione presse
- Gestione DPI e consegne`)
</script>

<template>
  <PrototypeShell section="Fascicolo">
    <template #actions><div class="actions"><span><i /> Salvato</span><UButton color="neutral" variant="outline" icon="i-lucide-history" label="Cronologia" /><UButton icon="i-lucide-save" label="Salva versione" /></div></template>
    <div class="layout-a">
      <section class="document"><div class="notice"><UIcon name="i-lucide-git-compare-arrows" /><span><strong>Revisione 4 disponibile</strong><small>Confronta la proposta prima di applicarla.</small></span><UButton color="warning" variant="outline" label="Confronta" /></div><article><header><small>FASCICOLO DI SICUREZZA</small><h1>Officine Bianchi</h1><p>Stabilimento nord · Torino</p></header><textarea v-model="text" aria-label="Fascicolo Markdown" spellcheck="false" /></article></section>
      <aside class="context"><section><h2>Incarico</h2><dl><div><dt>Modello</dt><dd>Fascicolo sicurezza aziendale</dd></div><div><dt>Revisione</dt><dd>3</dd></div><div><dt>Riferimento</dt><dd>29 settembre 2026</dd></div></dl></section><section><h2>Stato</h2><div class="completion"><span><i /></span><strong>72%</strong></div><ul><li><UIcon name="i-lucide-check" /> Anagrafica completa</li><li><UIcon name="i-lucide-check" /> Rischi acquisiti</li><li class="warn"><UIcon name="i-lucide-circle-alert" /> Formazione da completare</li></ul></section><section><h2>Indicazione attiva</h2><div class="instruction"><strong>2. Valutazione dei rischi</strong><p>Elencare solo le valutazioni applicabili e collegare il piano di miglioramento.</p></div></section></aside>
    </div>
  </PrototypeShell>
</template>

<style scoped>
.actions{display:flex;align-items:center;gap:7px}.actions>span{display:flex;align-items:center;gap:5px;color:#6d7871;font-size:8px}.actions i{width:5px;height:5px;border-radius:50%;background:#4d8a6c}.layout-a{display:grid;grid-template-columns:minmax(500px,1fr) 270px;min-height:calc(100vh - 68px)}.document{padding:18px 24px 70px;overflow-y:auto}.notice{display:flex;align-items:center;gap:9px;max-width:780px;margin:0 auto 12px;padding:9px 11px;border:1px solid #e3bd82;border-radius:4px;color:#955b23;background:#fffaf0}.notice>span{display:grid;flex:1}.notice strong{font-size:9px}.notice small{color:#8f755d;font-size:7px}.document article{max-width:780px;min-height:760px;margin:auto;padding:46px 58px;border:1px solid #dce0db;background:#fff}.document article header{padding-bottom:22px;border-bottom:1px solid #e1e4e0}.document article small{color:#27684e;font-size:7px;font-weight:700;letter-spacing:.14em}.document article h1{margin:8px 0 4px;font-family:Georgia,serif;font-size:27px;font-weight:400}.document article p{margin:0;color:#808983;font-size:8px}.document textarea{width:100%;min-height:560px;padding:25px 0;resize:none;border:0;outline:0;color:#2d3731;background:transparent;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10px;line-height:1.85}.context{border-left:1px solid #dce0db;background:#fafbf9}.context section{padding:18px;border-bottom:1px solid #e1e4e0}.context h2{margin:0 0 12px;font-size:9px}.context dl{display:grid;gap:9px;margin:0}.context dl div{display:grid;grid-template-columns:65px 1fr;gap:8px}.context dt{color:#89918c;font-size:7px}.context dd{margin:0;font-size:8px}.completion{display:flex;align-items:center;gap:8px}.completion span{flex:1;height:5px;background:#e2e6e2}.completion i{display:block;width:72%;height:100%;background:#347658}.completion strong{font-family:Georgia,serif;font-size:16px;font-weight:500}.context ul{display:grid;gap:7px;margin:13px 0 0;padding:0;list-style:none}.context li{display:flex;align-items:center;gap:6px;color:#54705f;font-size:8px}.context li.warn{color:#a26228}.instruction{padding:10px;border-radius:3px;background:#edf2ee}.instruction strong{font-size:8px}.instruction p{margin:5px 0 0;color:#6e7872;font-size:8px;line-height:1.5}@media(max-width:950px){.layout-a{grid-template-columns:1fr}.context{display:none}}@media(max-width:600px){.document{padding:12px}.document article{padding:30px 24px}.actions>span,.actions :deep(span){display:none}}
</style>
