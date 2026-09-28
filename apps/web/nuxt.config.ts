export default defineNuxtConfig({
  compatibilityDate: '2026-09-28',
  css: ['~/assets/css/main.css'],
  devtools: { enabled: false },
  runtimeConfig: {
    apiBase: 'http://127.0.0.1:8000',
  },
  typescript: { typeCheck: true },
})
