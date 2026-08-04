import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev proxy so the SPA can call relative /api URLs with no CORS and no cookie
// gymnastics — the auth cookie stays first-party.
const target = process.env.VITE_API_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target, changeOrigin: true } },
  },
});
