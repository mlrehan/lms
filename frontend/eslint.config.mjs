import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescriptRules from "eslint-config-next/typescript";

/**
 * Flat config. `eslint-config-next` 16 ships flat configs directly, so there
 * is no `FlatCompat` here -- routing them through the eslintrc compatibility
 * layer crashes on a circular plugin reference under ESLint 10.
 */
export default [
  ...coreWebVitals,
  ...typescriptRules,
  {
    rules: {
      // `any` disables the type checking this console leans on to keep its
      // API calls honest, so it is an error rather than a warning.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // Nothing in this console renders HTML from a string. The rule is on so
      // that stays true by accident as well as by intent.
      "react/no-danger": "error",
    },
  },
  { ignores: [".next/**", "node_modules/**", "coverage/**", "next-env.d.ts"] },
];
