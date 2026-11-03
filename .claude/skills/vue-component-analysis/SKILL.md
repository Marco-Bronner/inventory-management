---
name: vue-component-analysis
description: Analyzes the structure of Vue components in client/src/views and client/src/components and suggests optimizations for performance and code reuse. Use when asked to review Vue components, find duplicated logic, oversized components, missing computed caching, v-for key problems, watcher misuse, prop drilling or heavy inline SVG charts.
---

# Vue Component Analysis

Read-only analysis of the Vue 3 client. Produces a findings report with `file:line` references and a concrete suggestion per finding. It does not change code unless the user asks for the fixes afterwards.

## Scope

- `client/src/views/*.vue` and `client/src/components/*.vue`
- Context only (do not report on them, read when needed): `client/src/composables/`, `client/src/utils/`, `client/src/api.js`, `client/src/App.vue`

## Procedure

1. **Scan.** Run `node .claude/skills/vue-component-analysis/scan.mjs` from the repo root. It prints per-file size (template / script / style lines), helper functions defined in more than one file, and smell candidates with `file:line` (v-for keys, watchers, `.find` in loops, console.log, inline SVG). Treat its output as candidates, never as findings.
2. **Confirm.** Open each candidate with Read at that line. Drop false positives. For the checks below that the scan does not cover, use Grep.
3. **Rate.** Give each finding an impact (High / Medium / Low) and an effort (S / M / L), see rubric.
4. **Report.** Write the findings in the format below. If the user named an output file, write there, otherwise answer in chat.

## Checks

| # | Check | How to find it | What to suggest |
|---|-------|----------------|-----------------|
| 1 | **Oversized component** | Total > 400 lines or script > 250 lines; template with several `card` sections; many `ref` blocks for modal state | Split into section components (one per card/chart/table) and extract logic into a `use<Feature>` composable |
| 2 | **Duplicated logic that belongs in a composable** | Scan output "same helper defined in several files"; also grep `translate`, `format`, `currencySymbol`, `getStockStatus`, load + `watch` on filters | Move to `composables/` or `utils/`; name after the job (`useFormatters`, `useStockStatus`) |
| 3 | **Missing computed caching** | Functions called from the template with data arguments (`getX(...)` inside `v-for` or in several places), `.filter/.sort/.reduce` inside methods called per render, derived values stored in `data`/`ref` and recalculated by hand | Replace with `computed`; compute once, e.g. a `Map`/`Set` for lookups |
| 4 | **v-for keys** | `v-for` without `:key`, `:key="index"`/`idx` on lists that can change or reorder, key on the wrong element | Use a stable id (`id`, `sku`, `month`); index is acceptable only for static lists that never change |
| 5 | **Watchers vs computed** | Every `watch(`: does it only derive a value (use `computed`), do nothing (delete), or really trigger a side effect such as a fetch (keep, consider `watch` with `immediate` instead of a separate `onMounted`) | Replace derive-only watchers with `computed`, remove empty ones |
| 6 | **Prop drilling** | Same prop passed through 2+ levels, `selectedX` props handed down, modal props duplicated per parent. Check how state is shared today (singleton composables count as OK) | `provide/inject` or a composable with shared state |
| 7 | **Large inline SVG charts** | `<svg>` with several `<circle>/<path>/<polyline>` in a view template, repeated arithmetic in attributes, hard-coded colors; repeated icon SVGs across files | Extract a chart component (`DonutChart`, `BarChart`) with props; icons into one `icons/` component set; compute segment geometry once in a `computed` |
| 8 | **Large lookups in loops** | `.find(` / `.includes(` inside `forEach`/`map` over orders or inventory | Build a `Map`/`Set` once in a `computed` |
| 9 | **Style duplication** | Same class blocks (for example `.modal-overlay`, `.modal-container`) in several SFCs | Shared modal base component or a global stylesheet |
| 10 | **Leftovers hurting performance** | `console.log` in render-path methods, API calls that bypass `api.js`, hard-coded URLs | Remove, route through `api.js` |

## Rating rubric

- **High**: affects every render or every user (render-path functions, O(n^2) in computed, dead feature), or blocks reuse across 4+ files.
- **Medium**: duplication in 2-3 files, oversized component that is hard to change.
- **Low**: style or consistency only.

## Output format

```
# Vue component analysis
Scope, date, files scanned, command used.

## Summary
Table: # | Finding | Impact | Effort | Location

## Findings
### <n>. <title> (<Impact>, <Effort>)
- Where: path:line (all locations)
- Problem: one or two sentences
- Suggestion: concrete change, optionally a short snippet

## Not found / checked and fine
One line per check with no findings (so the reader knows it was looked at).

## Suggested order
Numbered list, quick wins first.
```

## Rules

- Every finding has at least one `file:line` that you opened and verified.
- Do not recommend a library when a 10-line composable does the job.
- Respect project conventions in `CLAUDE.md` and `client/CLAUDE.md` (Composition API, unique keys, raw data in refs, derived data in computed).
- Do not edit `.vue` files as part of the analysis. Fixes to `.vue` files go through the `vue-expert` agent.
- Report only what is in the code. Mark anything you did not measure at runtime as an estimate.
