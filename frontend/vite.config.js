import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The project keeps its shared local configuration at the repository root.
  // Without this, Vite only checks frontend/.env and Google sign-in falls back
  // to the disabled authentication client during local development.
  envDir: '..',
  server: {
    port: 5173
  }
})
