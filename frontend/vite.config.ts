import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API owns /api/v2 (and /docs). In dev the Vite server (5174) proxies those
// to the FastAPI backend (8010); in production `npm run build` emits dist/ which
// the same FastAPI app serves at /. Ports are deliberately off the common
// 5173/8000 so this never collides with another project running locally.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8010", changeOrigin: true },
      "/docs": { target: "http://127.0.0.1:8010", changeOrigin: true },
      "/openapi.json": { target: "http://127.0.0.1:8010", changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
