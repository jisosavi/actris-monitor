import './assets/main.css'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'
import App from './App.vue'

const app = createApp(App)
app.use(createPinia())
app.use(VueQueryPlugin)
app.mount('#app')
