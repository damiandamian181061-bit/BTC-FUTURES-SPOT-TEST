// After `vite build`: copy data/paper/dashboard.json into dist/data/ so the built site works from any static server.
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '../../data/paper/dashboard.json')
const dst = resolve(here, '../dist/data/dashboard.json')
mkdirSync(dirname(dst), { recursive: true })
if (existsSync(src)) {
  copyFileSync(src, dst)
  console.log(`copied ${src} -> ${dst}`)
} else {
  console.log(`no ${src} yet: run "python3 code/dashboard.py" first; the built site will show "no data" until then`)
}
