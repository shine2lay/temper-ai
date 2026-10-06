import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// Safe rendering: content (agent output above all) is shown as React text,
// never parsed as HTML, and markdown goes through one shared renderer.
const SAFE_MARKDOWN = 'src/components/shared/SafeMarkdown.tsx'
const USE_SAFE_MARKDOWN = `Render content with SafeMarkdown (${SAFE_MARKDOWN}) or as React text; never as an HTML string.`
const HTML_SINK_PROPS = /^(innerHTML|outerHTML|srcdoc)$/
const HTML_SINK_CALLS = /^(insertAdjacentHTML|createContextualFragment|setHTMLUnsafe|parseHTMLUnsafe)$/

const htmlSinks = [
  { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: `dangerouslySetInnerHTML is not allowed. ${USE_SAFE_MARKDOWN}` },
  { selector: "Property[key.name='dangerouslySetInnerHTML']", message: `dangerouslySetInnerHTML is not allowed. ${USE_SAFE_MARKDOWN}` },
  { selector: `MemberExpression[property.name=${HTML_SINK_PROPS}]`, message: `innerHTML, outerHTML and srcdoc are not allowed. ${USE_SAFE_MARKDOWN}` },
  { selector: `MemberExpression[computed=true][property.value=${HTML_SINK_PROPS}]`, message: `innerHTML, outerHTML and srcdoc are not allowed. ${USE_SAFE_MARKDOWN}` },
  { selector: `CallExpression[callee.property.name=${HTML_SINK_CALLS}]`, message: `Building DOM from an HTML string is not allowed. ${USE_SAFE_MARKDOWN}` },
  { selector: "CallExpression[callee.object.name='document'][callee.property.name=/^(write|writeln)$/]", message: `document.write is not allowed. ${USE_SAFE_MARKDOWN}` },
  { selector: "Identifier[name='DOMParser']", message: `DOMParser is not allowed. ${USE_SAFE_MARKDOWN}` },
  { selector: 'JSXAttribute[name.name=/^srcdoc$/i]', message: `srcDoc is not allowed. ${USE_SAFE_MARKDOWN}` },
]

const markdownImports = {
  paths: [
    { name: 'react-markdown', message: `Import SafeMarkdown instead: ${SAFE_MARKDOWN} is the only react-markdown user.` },
    { name: 'rehype-raw', message: `Raw HTML stays literal text. ${USE_SAFE_MARKDOWN}` },
    { name: 'rehype', message: `No rehype pipeline. ${USE_SAFE_MARKDOWN}` },
    { name: 'remark-rehype', message: `No rehype pipeline. ${USE_SAFE_MARKDOWN}` },
    { name: 'hast-util-raw', message: `Raw HTML stays literal text. ${USE_SAFE_MARKDOWN}` },
  ],
  patterns: [
    { group: ['rehype-*'], message: `No rehype plugins. ${USE_SAFE_MARKDOWN}` },
  ],
}

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      'no-restricted-imports': ['error', markdownImports],
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/__tests__/**', 'src/**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', ...htmlSinks],
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
    },
  },
  {
    // The one renderer: it alone may import react-markdown. Every other ban still holds.
    files: [SAFE_MARKDOWN],
    rules: {
      'no-restricted-imports': ['error', {
        paths: markdownImports.paths.filter((p) => p.name !== 'react-markdown'),
        patterns: markdownImports.patterns,
      }],
    },
  },
])
