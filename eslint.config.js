import js from '@eslint/js';
import globals from 'globals';
import html from 'eslint-plugin-html';

export default [
  { ignores: ['node_modules/', '.venv/', 'test-results/', 'playwright-report/'] },
  js.configs.recommended,
  {
    // The viewer deliberately swallows errors from best-effort calls (worker teardown,
    // an optional /models endpoint); an unused catch binding or empty catch is fine.
    rules: {
      'no-unused-vars': ['error', { caughtErrors: 'none', argsIgnorePattern: '^_' }],
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
  {
    // The viewer: browser scripts, including the inline <script> blocks of index.html.
    files: ['**/*.html', 'src/**/*.js'],
    plugins: { html },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: globals.browser,
    },
  },
  {
    // The viewer modules stay small enough to review and test: no file over 500 lines,
    // no function over 75 (both counted with comments and blank lines).
    files: ['src/**/*.js'],
    rules: {
      'max-lines': ['error', { max: 500 }],
      'max-lines-per-function': ['error', { max: 75 }],
    },
  },
  {
    // Tooling and Node-side tests.
    files: ['*.js', '*.mjs', 'tests/**/*.js', 'tests/**/*.mjs'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: globals.node,
    },
  },
];
