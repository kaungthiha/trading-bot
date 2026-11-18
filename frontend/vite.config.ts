/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Production builds get a strict CSP. (Not in dev: Vite's React refresh preamble is an
// inline script.) style-src allows inline style attributes used for tooltip positioning.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
].join("; ");

function cspPlugin(): Plugin {
  return {
    name: "krt-csp",
    apply: "build",
    transformIndexHtml(html) {
      return html.replace(
        "<head>",
        `<head>
    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`,
      );
    },
  };
}

const API_TARGET = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), cspPlugin()],
  // Only VITE_-prefixed variables are ever exposed to the bundle. Never put secrets in
  // VITE_* variables; the browser holds no credentials in this app.
  envPrefix: "VITE_",
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: API_TARGET, changeOrigin: false } },
  },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  build: { sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
