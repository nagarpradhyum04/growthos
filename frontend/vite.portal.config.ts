import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Customer portal: a separate app on its own port (default 5174), same API and database as the
// business app. Customers sign in with the Business ID their supplier gave them + their email.
export default defineConfig({
  root: resolve(__dirname, "portal-app"),
  plugins: [react()],
  server: {
    port: 5174,
    fs: { allow: [resolve(__dirname)] },
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_URL ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: { outDir: resolve(__dirname, "dist-portal"), emptyOutDir: true },
});
