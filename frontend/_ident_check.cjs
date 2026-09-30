const fs = require('fs')
const path = require('path')
const { parse } = require('@vue/compiler-sfc')

const files = process.argv.slice(2)
const BUILTIN = new Set(['true', 'false', 'null', 'undefined', 'this', 'Math', 'Date', 'JSON', 'String', 'Number', 'Array', 'Object', 'parseInt', 'parseFloat', 'isNaN', 'confirm', 'alert', 'window', 'document', 'localStorage', 'location', 'navigator', 'console', 'Promise', 'Set', 'Map', 'URL', 'URLSearchParams', 'FormData', 'Response', 'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval'])

for (const file of files) {
  const filename = path.resolve(file)
  const source = fs.readFileSync(filename, 'utf-8')
  const { descriptor } = parse(source, { filename })
  const script = (descriptor.scriptSetup ? descriptor.scriptSetup.content : '') +
    (descriptor.script ? descriptor.script.content : '')
  const tmpl = descriptor.template ? descriptor.template.content : ''

  // collect identifiers from event handlers / bindings / mustaches
  const idents = new Set()
  const attrRe = /(?:@[\w.]+|:[\w.-]+)\s*=\s*"([^"]*)"/g
  let m
  while ((m = attrRe.exec(tmpl))) exprCapture(m[1], idents)
  const mustRe = /\{\{([\s\S]*?)\}\}/g
  while ((m = mustRe.exec(tmpl))) exprCapture(m[1], idents)

  const missing = []
  for (const id of idents) {
    if (BUILTIN.has(id)) continue
    if (/^\d/.test(id)) continue
    // declared in script?
    const declRe = new RegExp(`(?:const|let|var|function|import)\\s+${id}\\b|${id}\\s*=`)
    if (declRe.test(script)) continue
    // could be a local of inline handler (we can't tell) - check for single-letter loop vars handled in exprCapture filter
    missing.push(id)
  }
  console.log(`--- ${file}`)
  if (missing.length) console.log('   maybe-missing:', missing.join(', '))
  else console.log('   all identifiers found')
}

function exprCapture(expr, out) {
  const re = /[A-Za-z_$][\w$]*/g
  let mm
  while ((mm = re.exec(expr))) {
    const id = mm[0]
    if (id.length === 1) continue // assume loop/local var
    out.add(id)
  }
}
