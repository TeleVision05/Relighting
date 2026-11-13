import js from '@eslint/js';
import globals from 'globals';
import html from 'eslint-plugin-html';

export default [
  { ignores: ['node_modules/', '.venv/', 'test-results/', 'playwright-report/'] },
  js.configs.recommended,
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
    // Tooling and Node-side tests.
    files: ['*.js', '*.mjs', 'tests/**/*.js', 'tests/**/*.mjs'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: globals.node,
    },
  },
];
