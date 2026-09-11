import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // Native since Vite 8, which is why vite-tsconfig-paths is not a dependency here.
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    include: ["{app,lib,features,components,actions}/**/*.test.{ts,tsx}"],
  },
});
