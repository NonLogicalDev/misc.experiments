import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({
  build: {
    lib: {
      entry: resolve(__dirname, "src/extension.ts"),
      formats: ["cjs"],
      fileName: () => "extension.js",
    },
    outDir: "dist",
    sourcemap: true,
    minify: false,
    rollupOptions: {
      external: [
        "vscode",
        // Node.js built-in modules
        "path",
        "fs",
        "os",
        "child_process",
        "util",
        "events",
        "stream",
        "buffer",
        "url",
        "querystring",
        "crypto",
        "http",
        "https",
        "net",
        "tls",
        "zlib",
      ],
      output: {
        entryFileNames: "extension.js",
        format: "cjs",
        exports: "named",
      },
    },
    commonjsOptions: {
      transformMixedEsModules: true,
    },
  },
  resolve: {
    extensions: [".ts", ".js"],
  },
});
