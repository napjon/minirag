import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const proxy = {
  "/v1": { target: "http://127.0.0.1:8130", changeOrigin: true },
  "/health": { target: "http://127.0.0.1:8130", changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3130,
    host: "127.0.0.1",
    strictPort: true,
    proxy,
  },
  preview: {
    port: 3130,
    host: "127.0.0.1",
    strictPort: true,
    proxy,
  },
});
