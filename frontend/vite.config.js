import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VERIFY: defineConfig/plugin-react usage against current Vite docs if
// this errors on setup — Vite's config API has been stable across recent
// versions as far as I'm aware, but confirm for whatever version installs.
export default defineConfig({
  plugins: [react()],
});
