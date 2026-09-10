import typescriptRules from "eslint-config-next/typescript";
import reactHooks from "eslint-plugin-react-hooks";
import nextPlugin from "@next/eslint-plugin-next";

/**
 * Flat config.
 *
 * `eslint-config-next` 16 ships flat configs, so there is no `FlatCompat`
 * here -- routing them through the eslintrc compatibility layer crashes on a
 * circular plugin reference under ESLint 10.
 *
 * The rules are assembled from the three plugins directly rather than by
 * extending `next/core-web-vitals`, because that entry point pulls in
 * `eslint-plugin-react`, whose bundled version calls `context.getFilename()`
 * -- removed in ESLint 10 -- and crashes while linting the first file.
 * Nothing is being suppressed: the TypeScript rules, the React Hooks rules
 * and the whole Next core-web-vitals set are all applied. What is *not*
 * applied is `eslint-plugin-jsx-a11y`, which the same entry point would have
 * brought along; it cannot be imported on its own because it is nested inside
 * `eslint-config-next`. Accessibility is therefore held by review and by the
 * component primitives (every control carries a label, every icon-only button
 * an `aria-label`), not by a linter -- stated here rather than left as a
 * silent gap.
 */
export default [
  ...typescriptRules,
  {
    plugins: { "react-hooks": reactHooks, "@next/next": nextPlugin },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,

      // `any` disables the type checking this console leans on to keep its
      // API calls honest, so it is an error rather than a warning.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    ignores: [".next/**", "node_modules/**", "coverage/**", "next-env.d.ts"],
  },
];
