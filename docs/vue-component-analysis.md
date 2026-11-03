# Vue component analysis

Scope: `client/src/views/*.vue` (7 files) and `client/src/components/*.vue` (9 files). Procedure: `.claude/skills/vue-component-analysis/SKILL.md` (scan with `scan.mjs`, then confirmed by reading each location). Static analysis only, nothing measured at runtime.

## Summary

| # | Finding | Impact | Effort | Main location |
|---|---------|--------|--------|---------------|
| 1 | Reports: render-path methods with O(n^2) work and `console.log` per bar/cell, derived stats kept in `data` | High | S | `Reports.vue:214-271`, `55-56`, `145-176` |
| 2 | Dashboard is 1272 lines (template 297, script 429, style 544) | High | L | `Dashboard.vue:1-1272` |
| 3 | Same helpers copied into many files (`translateCategory`, `formatDate`, `currencySymbol`, stock status, `translatePriority`) | Medium | M | see finding 3 |
| 4 | Donut chart as 5 hand-written `<circle>` with repeated arithmetic | Medium | S | `Dashboard.vue:87-106` |
| 5 | Lookup inside nested loop (`inventoryItems.find` per order item) | Medium | S | `Dashboard.vue:501` |
| 6 | Template calls `getForecastsByTrend()` 6 times per render, plus "++" display bug | Medium | S | `Demand.vue:21-65` |
| 7 | `:key` is the loop index on lists with real ids | Medium | S | `Reports.vue:28,51,82`, `Orders.vue:57` |
| 8 | Watchers: one does nothing, five only trigger the same fetch pattern in each view | Low | S | `Spending.vue:374-376` and 5 more |
| 9 | Modal shell (overlay/container CSS + close icon) copied into 6 components | Medium | M | see finding 9 |
| 10 | Oversized: Spending (853), TasksModal (622), Reports (489), InventoryDetailModal (451) | Medium | M | see finding 10 |
| 11 | Hard-coded chart scale and goals | Low | S | `Spending.vue:386-389`, `Dashboard.vue:340-341` |

## Findings

### 1. Reports: expensive methods in the render path (High, S)
- Where: `Reports.vue:255-271` (`getBarHeight`), used at `Reports.vue:55`; `formatNumber` `214-240`; `formatMonth` `242-253`; derived stats `138-141` and `180-212`.
- Problem: `getBarHeight` is called once per bar and loops over all months to find the max every time (O(n^2) per render). It also runs `console.log` on every call; `formatNumber` and `formatMonth` do the same, so each re-render writes dozens of log lines (14 `console.log` in the file). `totalRevenue`, `avgMonthlyRevenue`, `totalOrders` and `bestQuarter` are copied into `data` by `calculateSummaryStats()` instead of being derived.
- Also: the file uses Options API with `var` and bypasses `api.js` with hard-coded URLs (`Reports.vue:156,162`), unlike all other views.
- Suggestion: compute `maxRevenue` once in a `computed`, make the four stats `computed`, delete the logs, use `toLocaleString` instead of the manual comma loop, move the two calls into `api.getQuarterlyReports()` / `api.getMonthlyTrends()`.

### 2. Dashboard is oversized (High, L)
- Where: `Dashboard.vue` (template `1-297`, script `299-727`, style `729-1272`).
- Problem: one component holds KPI cards, donut, category bars, order trend, backlog table, top-products table, three modals, and about 10 `computed` blocks (`343-559`). Hard to change and every state change re-evaluates a big template.
- Suggestion: split into `KpiCards`, `OrderHealthCard` (donut + metrics), `InventoryByCategoryCard`, `OrderTrendChart`, `BacklogTable`, `TopProductsTable`. Move the computed blocks to `composables/useDashboardMetrics.js` (`orderHealthMetrics` `368-404`, `categoryData` `406-446`, `orderTrendData` `453-480`, `topProducts` `489-546`). The three modal open/selected pairs (`322-329`, `643-673`) become one `useModalState`.

### 3. Duplicated helpers that belong in composables (Medium, M)
| Helper | Locations |
|--------|-----------|
| `translateCategory` | `Dashboard.vue:604`, `Inventory.vue:188`, `Spending.vue:429` (identical map in the first two) |
| `formatDate` | `Dashboard.vue:635`, `Orders.vue:146`, `Spending.vue:396`, `BacklogDetailModal.vue:115`, `ProductDetailModal.vue:115`, `ProfileDetailsModal.vue:88` |
| `currencySymbol` | `Inventory.vue:101`, `Orders.vue:92`, `Spending.vue:382`, `CostDetailModal.vue:104`, `InventoryDetailModal.vue:113`, `ProductDetailModal.vue:94` |
| `getStockStatus` / `getStockStatusClass` | `Inventory.vue:173,178` and `InventoryDetailModal.vue:144,155` (same 1.0x / 1.5x reorder thresholds as `getStockStatusKey` `Inventory.vue:121`; `Dashboard.vue:517` uses a third rule) |
| `translatePriority` | `Dashboard.vue:623`, `TasksModal.vue:223` |
| load-on-mount + filter `watch` + loading/error refs | `Dashboard.vue:561,676`, `Inventory.vue:152,169`, `Demand.vue:142,165`, `Orders.vue:108,128`, `Backlog.vue:111,138` |
- Suggestion: `useI18n` already owns `translateProductName`/`translateWarehouse`, add `translateCategory`, `translatePriority`, `formatDate`, `currencySymbol` there (or in `utils/format.js`); add `useStockStatus(item)`; add `useFilteredResource(fetcher)` which wraps loading/error/refetch on filter change.

### 4. Large inline SVG chart (Medium, S)
- Where: `Dashboard.vue:87-106`.
- Problem: four stacked `<circle>` elements with the same radius, circumference `408` hard-coded as a magic number (the code at `594-596` multiplies by `440`, so the two disagree), colors hard-coded, offsets summed by hand in the template (`98`, `102`), and `getCircleSegment` called about 10 times per render.
- Suggestion: `DonutChart.vue` with props `segments: [{value, color, label}]`; compute `[{dash, offset, color}]` once in a `computed` using `2 * Math.PI * 65` for the circumference. The legend (`107-112`) can be rendered from the same array with `v-for`. The repeated 20x20 / 24x24 icon SVGs (21 occurrences, e.g. close icon at line 9-10 in six modals) should become small icon components.

### 5. `.find` inside nested loop (Medium, S)
- Where: `Dashboard.vue:501` inside `allOrders.forEach` / `order.items.forEach` (`494-496`).
- Problem: O(orders x items x inventory) on every filter change. Likewise `backlogItems` rebuilds a `Set` on each recompute (`557`), same pattern in `Demand.vue:138`.
- Suggestion: `const inventoryBySku = computed(() => new Map(inventoryItems.value.map(i => [i.sku, i])))` and use `.get(sku)`.

### 6. Function calls in `v-for` and double plus sign (Medium, S)
- Where: `Demand.vue:21,40,59` (and the `.length` checks at `25,44,63`), `getForecastsByTrend` defined `169-171`.
- Problem: each call filters the full list again, 6 filters per render. Also `getChangePercent` (`173-176`) already prefixes `+` for positive values, but the template adds another `+` (`Demand.vue:23`), so increasing items render as `++x%`.
- Suggestion: one `computed` that groups by trend (`{ increasing, stable, decreasing }`), template reads `grouped.increasing.slice(0, 5)`; drop the extra `+` in the template.

### 7. Index as `:key` (Medium, S)
- Where: `Reports.vue:28` (`quarterlyData`), `Reports.vue:51` and `82` (`monthlyData`), `Orders.vue:57` (`order.items`).
- Problem: contradicts the rule in `CLAUDE.md` ("use unique keys ... not index"). Items have `quarter`, `month`, `sku`.
- Suggestion: `:key="q.quarter"`, `:key="month.month"`, `:key="item.sku"`.
- Checked and fine: all other 14 `v-for` have stable keys (`id`, `sku`, `month`, `category`, `name`).

### 8. Watchers (Low, S)
- Where: `Spending.vue:374-376` (empty callback, only a comment saying computed properties update themselves) - delete it.
- The other five (`Dashboard.vue:676`, `Orders.vue:128`, `Inventory.vue:169`, `Demand.vue:165`, `Backlog.vue:138`) are legitimate side effects (refetch on filter change), but are the same code five times: see finding 3 (`useFilteredResource`), which also lets you drop the separate `onMounted(load)` via `watch(..., { immediate: true })`.
- `useI18n()` is called inside functions at `Dashboard.vue:637`, `Orders.vue:147`, `Demand.vue:194`. Works because the state is module-level, but call it once in `setup()` and reuse `currentLocale`.

### 9. Modal shell duplicated (Medium, M)
- Where: `.modal-overlay` / `.modal-container` CSS in `CostDetailModal.vue:153,167`, `TasksModal.vue:248,261`, `InventoryDetailModal.vue:178,192`, `BacklogDetailModal.vue:127,141`, `ProductDetailModal.vue:134,148`, `ProfileDetailsModal.vue:100,114`; the template header with the close icon repeats at line 9-10 in each.
- Suggestion: one `BaseModal.vue` with slots (`header`, default, `footer`) and `isOpen`/`close`; each modal only supplies content. Removes roughly 100 lines of CSS per file.

### 10. Oversized files (Medium, M)
| File | Lines (tpl / script / style) | Split by |
|------|------------------------------|----------|
| `Spending.vue` | 853 (172 / 319 / 360) | revenue chart, cost chart, category list, transactions table; revenue/profit computeds `296-348` to a composable |
| `TasksModal.vue` | 622 (119 / 125 / 376) | `TaskList`, `TaskForm`, shared `BaseModal` |
| `Reports.vue` | 489 (125 / 191 / 171) | see finding 1 |
| `InventoryDetailModal.vue` | 451 (105 / 69 / 275) | shared modal CSS (finding 9) |
- Styles are the largest part in 6 of the 7 largest files, so finding 9 plus shared style tokens give the biggest line reduction.

### 11. Hard-coded scale and values (Low, S)
- `Spending.vue:386-389`: `getBarHeight` uses a fixed `25000` max, so bars overflow or flatten when data changes; use the max of `monthlySpending` like `getRevenueBarHeight` does.
- `Dashboard.vue:340-341`: `ordersData` (187 / 200) and `fillRate` (96.8) are fixed demo numbers; check whether they should come from `summary`.
- `Dashboard.vue:151`: non-JPY values hard-code `$` and a `K` suffix, bypassing `formatCurrency`.

## Checked, no finding
- **Prop drilling**: none. Shared state goes through singleton composables (`useFilters`, `useI18n`, `useAuth`), and modals receive props only one level down from their view (`App.vue` to `TasksModal`, `Dashboard` to the three modals).
- **Missing keys**: none (see finding 7 for index keys).

## Suggested order
1. Reports quick wins (finding 1) and keys (7): small, visible, no risk.
2. `inventoryBySku` map (5) and Demand grouping (6, includes a display bug).
3. `BaseModal` (9), shared helpers (3), `DonutChart` (4).
4. Dashboard and Spending split (2, 10) after the above, since the pieces are then small.
