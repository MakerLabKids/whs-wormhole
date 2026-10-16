import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

// Tests run inside workerd with real (local) D1 + R2 bindings taken from the
// local wrangler config: same bindings as production, a test-only assets dir,
// dummy secrets as vars.
export default defineConfig({
  plugins: [cloudflareTest({ wrangler: { configPath: "./wrangler.local.jsonc" } })],
});
