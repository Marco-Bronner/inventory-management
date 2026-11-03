<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <label class="budget-label" for="budget-slider">
          {{ t('restocking.budget') }}: <strong>{{ money(budget) }}</strong>
        </label>
        <input
          id="budget-slider"
          class="budget-slider"
          type="range"
          min="0"
          :max="maxBudget"
          :step="step"
          v-model.number="budget"
        />
        <div class="budget-range">
          <span>{{ money(0) }}</span>
          <span>{{ money(maxBudget) }}</span>
        </div>
        <p class="hint">{{ t('restocking.budgetHint') }}</p>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.itemsCount') }}</div>
          <div class="stat-value">{{ recommendation.items.length }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ money(recommendation.total_cost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ money(recommendation.remaining_budget) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
          <button
            class="place-order"
            :disabled="submitting || recommendation.items.length === 0"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="message" :class="['message', message.type]">{{ message.text }}</div>

        <div v-if="recommendation.items.length === 0" class="empty">{{ t('restocking.noItems') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.shortfall') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in recommendation.items" :key="item.sku">
                <td><strong>{{ item.sku }}</strong></td>
                <td>{{ translateProductName(item.name) }}</td>
                <td><span :class="['badge', item.trend]">{{ t('trends.' + item.trend) }}</span></td>
                <td class="num">{{ item.shortfall }}</td>
                <td class="num">{{ item.quantity }}</td>
                <td class="num">{{ money(item.unit_cost, 2) }}</td>
                <td class="num"><strong>{{ money(item.line_total, 2) }}</strong></td>
                <td class="num">{{ t('restocking.days', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr>
                <td colspan="6" class="num"><strong>{{ t('restocking.totalCost') }}</strong></td>
                <td class="num"><strong>{{ money(recommendation.total_cost, 2) }}</strong></td>
                <td></td>
              </tr>
              <tr>
                <td colspan="6" class="num">{{ t('restocking.remaining') }}</td>
                <td class="num">{{ money(recommendation.remaining_budget, 2) }}</td>
                <td></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, currentLocale, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const message = ref(null)
    const maxBudget = ref(0)
    const budget = ref(0)
    const recommendation = ref({ items: [], total_cost: 0, remaining_budget: 0 })

    // Slider granularity: about 200 steps over the range
    const step = computed(() => Math.max(1, Math.round(maxBudget.value / 200)))

    const money = (amount, decimals = 0) =>
      formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)

    let timer = null
    let requestId = 0
    const loadRecommendation = async () => {
      const id = ++requestId
      try {
        const data = await api.getRestockingRecommendations(budget.value)
        if (id === requestId) recommendation.value = data
      } catch (err) {
        error.value = 'Failed to load restocking data: ' + err.message
      }
    }

    watch(budget, () => {
      clearTimeout(timer)
      timer = setTimeout(loadRecommendation, 120)
    })

    const placeOrder = async () => {
      submitting.value = true
      message.value = null
      try {
        const order = await api.createRestockingOrder({
          items: recommendation.value.items.map(i => ({ sku: i.sku, quantity: i.quantity })),
          budget: budget.value
        })
        const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
        const date = new Date(order.expected_delivery + 'T00:00:00').toLocaleDateString(locale, {
          year: 'numeric', month: 'short', day: 'numeric'
        })
        message.value = { type: 'success', text: t('restocking.orderPlaced', { id: order.id, date }) }
      } catch (err) {
        const detail = err.response?.data?.detail || err.message
        message.value = { type: 'error', text: t('restocking.orderFailed', { message: detail }) }
      } finally {
        submitting.value = false
      }
    }

    onMounted(async () => {
      try {
        const full = await api.getRestockingRecommendations(0)
        maxBudget.value = Math.ceil(full.max_budget)
        budget.value = Math.round(maxBudget.value / 2)
        await loadRecommendation()
      } catch (err) {
        error.value = 'Failed to load restocking data: ' + err.message
      } finally {
        loading.value = false
      }
    })

    onBeforeUnmount(() => clearTimeout(timer))

    return {
      t,
      loading,
      error,
      submitting,
      message,
      maxBudget,
      budget,
      step,
      recommendation,
      money,
      placeOrder,
      translateProductName
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-label {
  display: block;
  margin-bottom: 0.75rem;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
}

.budget-range {
  display: flex;
  justify-content: space-between;
  color: #64748b;
  font-size: 0.8rem;
}

.hint {
  margin: 0.5rem 0 0;
  color: #64748b;
  font-size: 0.85rem;
}

.num {
  text-align: right;
}

.place-order {
  background: #0f172a;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1.25rem;
  font-weight: 600;
  cursor: pointer;
}

.place-order:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.message {
  margin: 0 1.5rem 1rem;
  padding: 0.6rem 0.9rem;
  border-radius: 6px;
  font-size: 0.9rem;
}

.message.success {
  background: #dcfce7;
  color: #166534;
}

.message.error {
  background: #fee2e2;
  color: #991b1b;
}

.empty {
  padding: 1.5rem;
  color: #64748b;
}

tfoot td {
  border-top: 1px solid #e2e8f0;
}
</style>
