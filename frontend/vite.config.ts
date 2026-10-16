import { defineConfig } from "vite";

export default defineConfig({
  server: {
    strictPort: true,
    proxy: {
      "/api": process.env.AUTOTRADER_API_PROXY ?? "http://127.0.0.1:8000",
      "/healthz": process.env.AUTOTRADER_API_PROXY ?? "http://127.0.0.1:8000",
      "/readyz": process.env.AUTOTRADER_API_PROXY ?? "http://127.0.0.1:8000",
    },
  },
});
