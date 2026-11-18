import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Local backend origin for the dev proxy. The project runs Django on 8010
// (port 8000 is reserved on some Windows machines); override with
// VITE_DEV_API_TARGET if you run it elsewhere.
const DEV_API_TARGET = process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8010"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    host: true,
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": { target: DEV_API_TARGET, changeOrigin: true },
      "/media": { target: DEV_API_TARGET, changeOrigin: true },
      "/static": { target: DEV_API_TARGET, changeOrigin: true },
    },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Stable vendor chunks: the browser caches them across releases and
        // only re-downloads the app code that actually changed. The charting
        // and camera-scanner libraries are large and only needed on a few
        // routes, so they get their own chunks and load on demand.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined
          if (
            id.includes("/react/") ||
            id.includes("/react-dom/") ||
            id.includes("/scheduler/") ||
            id.includes("/react-router")
          ) {
            return "react"
          }
          if (id.includes("framer-motion") || id.includes("motion-dom") || id.includes("motion-utils")) {
            return "motion"
          }
          if (id.includes("recharts") || id.includes("/d3-") || id.includes("victory-vendor")) {
            return "charts"
          }
          if (id.includes("html5-qrcode")) {
            return "scanner"
          }
          if (id.includes("@radix-ui")) {
            return "radix"
          }
          return undefined
        },
      },
    },
  },
})
