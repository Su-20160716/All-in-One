import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

// 回归门禁：只保留「语法/明显错误」类规则。历史代码里未使用变量很多，
// 一次性全开会淹没真正的解析错误，所以把风格类规则关掉。
export default [
  { ignores: ['dist/**', 'node_modules/**', 'public/**'] },
  js.configs.recommended,
  ...pluginVue.configs['flat/base'],
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
        __APP_BUILD__: 'readonly',
      },
    },
    rules: {
      'no-unused-vars': 'off',
      'no-undef': 'off',
      'no-empty': 'off',
      'no-constant-condition': 'off',
      // 中文文案里的全角空格、终端控制字符正则都是有意为之
      'no-irregular-whitespace': 'off',
      'no-control-regex': 'off',
    },
  },
]
