import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base: './' makes the build work from any subdirectory, which is what you
// want for a GitHub Pages project site (https://<user>.github.io/<repo>/).
export default defineConfig({
  base: './',
  plugins: [react()],
  build: { outDir: 'docs', chunkSizeWarningLimit: 4000 }
})
