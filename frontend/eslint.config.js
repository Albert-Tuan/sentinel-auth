import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'node_modules'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      eqeqeq: ['error', 'smart'],
    },
  },
  {
    // The Playwright suite is NOT React code.
    //
    // Two of the rules above misfire on it:
    //
    //   - `react-hooks/rules-of-hooks` complains about a fixture that
    //     is named `manifest` or `api` and calls `use()` — but `use`
    //     here is PLAYWRIGHT's use, not React's;
    //   - `no-empty-pattern` complains about Playwright's fixture
    //     signature `async ({}, use) => …`, which is the documented
    //     way to declare a fixture that depends on no other fixture.
    //
    // Turning the rules off for this directory is more honest than
    // renaming the fixtures to satisfy a React rule that does not
    // apply to them.
    files: ['e2e/**/*.{ts,tsx}'],
    rules: {
      'react-hooks/rules-of-hooks': 'off',
      'react-hooks/exhaustive-deps': 'off',
      'no-empty-pattern': 'off',
    },
  },
  {
    // Test files may use `any` and console freely.
    files: ['**/*.test.{ts,tsx}', 'src/test/**/*.{ts,tsx}'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      'no-console': 'off',
    },
  },
)
