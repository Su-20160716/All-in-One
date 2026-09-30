const fs = require('fs')
const path = require('path')
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc')

const files = process.argv.slice(2)
let failed = 0
for (const file of files) {
  const filename = path.resolve(file)
  let source
  try {
    source = fs.readFileSync(filename, 'utf-8')
  } catch (e) {
    console.log(`[READ-FAIL] ${file}: ${e.message}`)
    failed++
    continue
  }
  const { descriptor, errors } = parse(source, { filename })
  if (errors && errors.length) {
    failed++
    console.log(`[PARSE-FAIL] ${file}`)
    errors.forEach((e) => console.log('   ', e.message))
    continue
  }
  let bindings = {}
  if (descriptor.scriptSetup || descriptor.script) {
    try {
      const compiled = compileScript(descriptor, { id: 'check' })
      bindings = compiled.bindings || {}
    } catch (e) {
      failed++
      console.log(`[SCRIPT-FAIL] ${file}: ${e.message}`)
      continue
    }
  }
  if (descriptor.template) {
    const result = compileTemplate({
      source: descriptor.template.content,
      filename,
      id: 'check',
      compilerOptions: { bindingMetadata: bindings },
    })
    if (result.errors && result.errors.length) {
      failed++
      console.log(`[TEMPLATE-FAIL] ${file}`)
      result.errors.forEach((e) => console.log('   ', e.message || e))
      continue
    }
  }
  console.log(`[OK] ${file}`)
}
process.exit(failed ? 1 : 0)
