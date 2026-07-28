import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// The built bundle is served by the Python process from ui/dist, so asset paths
// must be relative. During development, vite serves the UI and proxies the API
// and WebSocket through to the headless backend on 8099.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: true },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8099", changeOrigin: true, ws: true },
    },
  },
});
