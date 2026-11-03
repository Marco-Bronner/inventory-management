#!/usr/bin/env node
// Quick structural scan of Vue SFCs. Usage: node scan.mjs [dir ...]  (default: client/src/views client/src/components)
// Prints per-file size split plus candidate smells with file:line. Candidates only: confirm by reading the code.
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const dirs = process.argv.slice(2)
if (!dirs.length) dirs.push('client/src/views', 'client/src/components')

const files = dirs.flatMap((d) =>
  readdirSync(d).filter((f) => f.endsWith('.vue')).map((f) => join(d, f))
)

const dup = new Map() // function name -> files
const rows = []
const smells = []

for (const file of files) {
  const lines = readFileSync(file, 'utf8').split(/\r?\n/)
  const at = (re) => lines.findIndex((l) => re.test(l)) + 1
  const tplEnd = at(/^<\/template>/)
  const scriptStart = at(/^<script/)
  const scriptEnd = at(/^<\/script>/)
  const styleStart = at(/^<style/)
  rows.push({
    file,
    total: lines.length,
    template: tplEnd,
    script: scriptStart ? scriptEnd - scriptStart + 1 : 0,
    style: styleStart ? lines.length - styleStart + 1 : 0,
    api: /export default/.test(lines.join('\n')) && !/<script setup/.test(lines.join('\n')) ? 'options/setup()' : 'script setup',
  })

  lines.forEach((l, i) => {
    const n = i + 1
    const loc = `${file}:${n}`
    const vfor = l.match(/v-for="([^"]+)"/)
    if (vfor) {
      const keyHere = /:key=/.test(l) || /:key=/.test(lines[i + 1] || '') || /:key=/.test(lines[i + 2] || '')
      if (!keyHere) smells.push(['v-for-no-key', loc, l.trim()])
      const idx = vfor[1].match(/\(\s*\w+\s*,\s*(\w+)\s*\)/)
      if (idx && new RegExp(`:key="${idx[1]}"`).test(l + (lines[i + 1] || ''))) smells.push(['v-for-index-key', loc, l.trim()])
      if (/\)\s*\.|\w+\(.*\)\s*\.slice|in \w+\([^)]*\)/.test(vfor[1])) smells.push(['v-for-calls-function', loc, vfor[1]])
    }
    if (/\bwatch\(/.test(l)) smells.push(['watcher', loc, l.trim()])
    if (/\.find\(/.test(l)) smells.push(['find-in-loop?', loc, l.trim()])
    if (/console\.log/.test(l)) smells.push(['console.log', loc, l.trim()])
    if (/useI18n\(\)/.test(l) && /^\s{6,}/.test(l)) smells.push(['composable-call-in-function?', loc, l.trim()])
    const fn = l.match(/^\s*(?:const|async)?\s*(translate\w+|format\w+|currencySymbol|getStock\w+)\s*(?:=|\()/)
    if (fn) {
      dup.set(fn[1], [...(dup.get(fn[1]) || []), loc])
    }
    if (/<svg/.test(l) && /viewBox="0 0 (14|18|20|24|48) /.test(l)) smells.push(['inline-icon-svg', loc, ''])
    if (/<circle|<polyline|<polygon/.test(l) && /stroke-dash|points=/.test(lines.slice(i, i + 4).join(' '))) smells.push(['inline-svg-chart', loc, l.trim().slice(0, 80)])
  })
}

console.log('== Size (lines)')
console.log('file'.padEnd(46), 'total tpl script style')
for (const r of rows.sort((a, b) => b.total - a.total)) {
  const flag = r.total > 400 ? '  <- oversized' : ''
  console.log(r.file.padEnd(46), String(r.total).padStart(5), String(r.template).padStart(4), String(r.script).padStart(6), String(r.style).padStart(5), flag)
}

console.log('\n== Same helper defined in several files (composable candidates)')
for (const [name, locs] of dup) if (locs.length > 1) console.log(name, '->', locs.join(', '))

console.log('\n== Smell candidates')
const grouped = {}
for (const [k, loc, txt] of smells) (grouped[k] ||= []).push(`${loc} ${txt}`)
for (const [k, items] of Object.entries(grouped)) {
  console.log(`\n[${k}] (${items.length})`)
  items.slice(0, 15).forEach((x) => console.log('  ' + x))
}
