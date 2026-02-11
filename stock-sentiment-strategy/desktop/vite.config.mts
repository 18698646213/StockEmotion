import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
  build: {
    outDir: 'dist',
  },
  resolve: {
    alias: {
      // react-plotly.js imports "plotly.js/dist/plotly" internally.
      // Redirect to the minified bundle (~1MB vs ~8MB full plotly.js).
      'plotly.js/dist/plotly': path.resolve(
        __dirname, 'node_modules/plotly.js-dist-min/plotly.min.js'
      ),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
})
