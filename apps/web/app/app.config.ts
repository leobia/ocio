export default defineAppConfig({
  ui: {
    colors: {
      primary: 'ocio',
      neutral: 'stone',
      warning: 'amber',
      error: 'red',
    },
    button: {
      defaultVariants: { size: 'sm' },
    },
    card: {
      slots: { root: 'ring-1 ring-default shadow-none' },
    },
  },
})
