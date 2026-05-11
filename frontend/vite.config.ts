import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig({
  server: {
    // Default to localhost so the dev server isn't reachable from the LAN.
    // For LAN testing (mobile QA, another machine on the network), run with
    // `npm run dev -- --host` or set VITE_DEV_HOST=0.0.0.0 in your shell.
    host: process.env.VITE_DEV_HOST || "localhost",
    port: 8080,
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
