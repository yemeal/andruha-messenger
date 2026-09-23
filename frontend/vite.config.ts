import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/api": {
        target: process.env.ANDRUHA_GATEWAY_URL || "http://127.0.0.1:8080",
        changeOrigin: true,
      },
      "/ws": {
        target: process.env.ANDRUHA_GATEWAY_URL || "http://127.0.0.1:8080",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
