import DefaultTheme from 'vitepress/theme'
import { defineClientComponent } from 'vitepress'
import './custom.css'

// The stock theme, retinted. No custom components and no layout overrides: the
// audience here reads Vite's and Vue's documentation daily, and a familiar shell
// is worth more than a distinctive one.
//
// The one exception is the Scalar reference, which has to be client-only —
// VitePress pre-renders every page and Scalar's component does not survive SSR.
export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component(
      'ScalarReference',
      defineClientComponent(() => import('./ScalarReference.vue')),
    )
  },
}
