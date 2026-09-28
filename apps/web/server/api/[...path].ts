export default defineEventHandler((event) => {
  const path = getRouterParam(event, 'path')
  if (!path) {
    throw createError({ statusCode: 404 })
  }
  const apiBase = useRuntimeConfig(event).apiBase.replace(/\/$/, '')
  return proxyRequest(event, `${apiBase}/${path}`)
})
