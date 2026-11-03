# Dashboard console errors

Collected with the `debugger` agent procedure: backend `uvicorn main:app --port 8031`, frontend `npx vite --port 3031`, Dashboard opened with `playwright-cli` (headless, in-memory profile). `client/src/api.js` hardcodes `http://localhost:8001/api` and `vite.config.js` has no proxy, so requests to 8001 were rewritten to 8031 inside the browser session (`page.route`). No app or config file was changed.

Result: 2 console errors and 2 warnings, which are 2 distinct problems. All other API calls on the Dashboard returned 200 (`/api/dashboard/summary`, `/api/orders`, `/api/inventory`, `/api/backlog`).

| # | Type | Message | Severity |
|---|------|---------|----------|
| 1 | Error (x2: network + caught) | `GET /api/tasks` 404, `Failed to load tasks: AxiosError` | Medium: Tasks modal never gets server data |
| 2 | Warning (x2) | `[Vue warn] Failed to resolve component: PurchaseOrderModal` | High: "Create PO" button on Dashboard opens nothing |

## 1. `/api/tasks` does not exist on the server

- **Symptom**: `Failed to load resource: 404` for `/api/tasks`, then `Failed to load tasks: AxiosError` from `App.vue`.
- **Root cause**: `client/src/api.js:77-95` defines `getTasks`, `createTask`, `deleteTask`, `toggleTask`, called from `client/src/App.vue:89-95` on mount (`App.vue:149`). `server/main.py` has only GET routes (`grep "@app\." server/main.py`); there is no `/api/tasks` and no POST/PATCH/DELETE route at all. Verified in the network log: `GET /api/tasks => 404`.
- **Suggested fix** (pick one):
  - Add task endpoints in `server/main.py` (GET list, POST, PATCH toggle, DELETE) backed by an in-memory list, with a Pydantic `Task` model matching what `TasksModal.vue` sends.
  - Or, if tasks are meant to be client-only for now, remove `onMounted(loadTasks)` at `App.vue:149` and keep local state.
- **Confidence**: verified.

## 2. `PurchaseOrderModal` is used but not imported or present

- **Symptom**: `[Vue warn] Failed to resolve component: PurchaseOrderModal` at `<Dashboard>`, repeated on re-render.
- **Root cause**: `client/src/views/Dashboard.vue:289` renders `<PurchaseOrderModal>`, but the imports (lines 305-306) and `components` (lines 310-312) contain only `ProductDetailModal` and `BacklogDetailModal`. `client/src/components/` has no `PurchaseOrderModal.vue`. The state and handlers exist (`showPOModal`, `openPOModal`, `viewPO`, `handlePOCreated`, around lines 327-329 and 653-673), as do `api.js:97-105` and `purchase_orders.json`, but the server has no `/api/purchase-orders` routes.
- **Suggested fix**: create `client/src/components/PurchaseOrderModal.vue` (props `isOpen`, `backlogItem`, `mode`; emits `close`, `po-created`), import and register it in `Dashboard.vue`, and add `GET/POST /api/purchase-orders` to `server/main.py`. Until then, hide the button at `Dashboard.vue:213-214` to avoid a dead click.
- **Confidence**: verified for the missing component (file absent, grep); server side by reading the `main.py` routes.

## Side observation (not a console error)

`client/src/api.js:3` hardcodes port 8001 and `server/main.py:309` hardcodes it for uvicorn, so other ports need an override. An env-based base URL (`import.meta.env.VITE_API_URL`) would make this configurable.

## Recommended order

1. Missing `PurchaseOrderModal` (user-visible dead feature).
2. `/api/tasks` endpoints (or remove the call).
3. Configurable API base URL.

Evidence screenshot: `dashboard-console-errors.png` (same folder).
