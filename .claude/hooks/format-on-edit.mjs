#!/usr/bin/env node
// PostToolUse hook (Edit|Write): runs prettier on the edited file.
// Reads the hook JSON from stdin (tool_input.file_path), falls back to $CLAUDE_FILE_PATH.
// Never fails the tool call: always exits 0, problems go to stderr only.
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve, extname, sep } from 'node:path'

const EXTENSIONS = new Set(['.js', '.mjs', '.cjs', '.ts', '.vue', '.json', '.css', '.html'])

async function readStdin() {
  if (process.stdin.isTTY) return ''
  let data = ''
  for await (const chunk of process.stdin) data += chunk
  return data
}

try {
  const raw = await readStdin()
  let filePath = process.env.CLAUDE_FILE_PATH || ''
  if (raw.trim()) {
    const payload = JSON.parse(raw)
    filePath = payload?.tool_input?.file_path || filePath
  }
  if (!filePath) process.exit(0)

  const projectDir = resolve(process.env.CLAUDE_PROJECT_DIR || process.cwd())
  const clientDir = resolve(projectDir, 'client')
  const abs = resolve(projectDir, filePath)

  // Only format client source files, never node_modules, and only existing files with known extensions.
  const inClient = abs.toLowerCase().startsWith((clientDir + sep).toLowerCase())
  if (!inClient || abs.includes(`${sep}node_modules${sep}`)) process.exit(0)
  if (!EXTENSIONS.has(extname(abs).toLowerCase()) || !existsSync(abs)) process.exit(0)

  // Use the project-local prettier binary through node (no shell, works on Windows and POSIX).
  const prettierBin = resolve(clientDir, 'node_modules', 'prettier', 'bin', 'prettier.cjs')
  if (!existsSync(prettierBin)) {
    console.error('format-on-edit: prettier not installed (run npm install in client/), skipped')
    process.exit(0)
  }
  const result = spawnSync(process.execPath, [prettierBin, '--write', abs], { cwd: clientDir, encoding: 'utf8' })
  if (result.status !== 0) {
    console.error(`format-on-edit: prettier failed for ${abs}: ${(result.stderr || '').trim().split('\n')[0]}`)
  }
} catch (err) {
  console.error(`format-on-edit: ${err.message}`)
}
process.exit(0)
