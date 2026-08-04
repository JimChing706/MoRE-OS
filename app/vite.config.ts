import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { inspectAttr } from 'kimi-plugin-inspect-react'

// https://vite.dev/config/
export default defineConfig({
  base: './',
  plugins: [inspectAttr(), react()],
  server: {
    port: 3002,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("commonjsHelpers") || id.startsWith("\0")) return "vendor-react"
          if (!id.includes("node_modules")) return
          if (/node_modules\/(react|react-dom|scheduler)(\/|$)/.test(id)) return "vendor-react"
          if (/node_modules\/@radix-ui\//.test(id)) return "vendor-radix"
          if (/node_modules\/(i18next|react-i18next|i18next-browser-languagedetector|lucide-react)(\/|$)/.test(id)) return "vendor-i18n-icons"
        },
      },
    },
  },
});
