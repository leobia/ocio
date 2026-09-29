export function useUnsavedChanges(dirty: Ref<boolean>) {
  const canLeave = () => !dirty.value || window.confirm('Ci sono modifiche non salvate. Vuoi abbandonarle?')
  onBeforeRouteLeave(canLeave)
  onBeforeRouteUpdate(canLeave)
  function beforeUnload(event: BeforeUnloadEvent) {
    if (!dirty.value) return
    event.preventDefault()
    event.returnValue = ''
  }
  onMounted(() => window.addEventListener('beforeunload', beforeUnload))
  onUnmounted(() => window.removeEventListener('beforeunload', beforeUnload))
}
