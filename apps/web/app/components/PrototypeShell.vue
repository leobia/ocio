<script setup lang="ts">
defineProps<{ section: string }>()
const router = useRouter()
</script>

<template>
  <div class="shell">
    <aside><a class="brand" href="/"><span>O</span><strong>OCIO</strong></a><nav><small>LAVORO</small><a class="active" href="#"><UIcon name="i-lucide-briefcase-business" /> Incarichi</a><a href="#"><UIcon name="i-lucide-files" /> Modelli</a><small>STRUMENTI</small><a href="/"><UIcon name="i-lucide-message-square-text" /> Assistente</a><a href="#"><UIcon name="i-lucide-library" /> Fonti</a></nav></aside>
    <main><header><div><UButton color="neutral" variant="ghost" icon="i-lucide-arrow-left" aria-label="Torna agli incarichi" @click="router.push('/incarichi')" /><span><small>Officine Bianchi · Torino</small><strong>{{ section }}</strong></span></div><slot name="actions" /></header><slot /></main>
  </div>
</template>

<style scoped>
.shell{min-height:100vh;display:grid;grid-template-columns:224px 1fr;color:#1d2420;background:#f5f6f3;font-family:Inter,ui-sans-serif,system-ui}.shell>aside{display:flex;height:100vh;flex-direction:column;padding:20px 14px;border-right:1px solid #d9ddd8;background:#ecefeb}.brand{display:flex;align-items:center;gap:10px;padding:0 8px 26px;color:inherit;text-decoration:none}.brand span{display:grid;place-items:center;width:32px;height:32px;border-radius:4px;color:#fff;background:#174f3b;font-family:Georgia,serif;font-size:18px}.brand strong{font-size:13px;letter-spacing:.14em}.shell nav{display:grid;gap:2px}.shell nav small{margin:19px 9px 6px;color:#838d87;font-size:8px;font-weight:700;letter-spacing:.12em}.shell nav a{display:flex;align-items:center;gap:9px;padding:9px;border-radius:4px;color:#5e6963;font-size:11px;text-decoration:none}.shell nav a.active{color:#174f3b;background:#fff}.shell>main{min-width:0}.shell>main>header{display:flex;align-items:center;justify-content:space-between;height:68px;padding:0 24px;border-bottom:1px solid #dde1dc;background:#fafbf9}.shell>main>header>div{display:flex;align-items:center;gap:8px}.shell>main>header span{display:grid}.shell>main>header small{color:#758078;font-size:8px}.shell>main>header strong{font-family:Georgia,serif;font-size:16px;font-weight:500}@media(max-width:800px){.shell{grid-template-columns:60px 1fr}.shell>aside{padding-inline:9px}.brand strong,.shell nav small,.shell nav a:not(.active){display:none}.brand{padding-inline:5px}.shell nav a{justify-content:center}}
</style>
