<script setup lang="ts">
import { computed } from 'vue'
import type { Ops } from '../api'
import { STATE_LABEL, time } from '../format'

const props = defineProps<{ ops: Ops; hot?: Set<string> }>()

const locName = computed(() => Object.fromEntries(props.ops.locations.map((l) => [l.id, l.name])))
const rows = computed(() =>
  props.ops.items.map((item) => {
    const assets = props.ops.assets.filter((a) => a.item_id === item.id && a.physical_state !== 'RETIRED')
    const w = props.ops.availability.windows.find((x) => x.item_id === item.id)
    const cond = new Map((w?.conditional_assets ?? []).map((c) => [c.asset_id, c.expected_ready_at]))
    const ready = new Set(w?.ready_asset_ids ?? [])
    return {
      item,
      total: assets.length,
      readyCount: ready.size,
      condCount: cond.size,
      assets: assets.map((a) => ({
        ...a,
        ready: ready.has(a.id),
        condAt: cond.get(a.id) ?? null,
        where: a.location_id ? locName.value[a.location_id] : '이동 중',
      })),
    }
  }),
)
</script>

<template>
  <section class="inv" aria-label="장비 재고">
    <header>
      <h2>장비 재고</h2>
      <p>물리 합계 <b class="num">{{ ops.total_assets }}</b>대 · {{ ops.date }} 기준 가용</p>
    </header>
    <div v-for="r in rows" :key="r.item.id" class="item">
      <div class="name">
        <strong>{{ r.item.model_name }}</strong>
        <span class="num">총 {{ r.total }} · 오늘 바로 출고 {{ r.readyCount }}<template v-if="r.condCount"> · 회수 후 가능 {{ r.condCount }}</template></span>
      </div>
      <ul>
        <li v-for="a in r.assets" :key="a.id" :title="`${STATE_LABEL[a.physical_state] ?? a.physical_state} · ${a.where}`">
          <span class="asset-tag" :class="{ muted: !a.ready && !a.condAt, cond: !!a.condAt, hot: hot?.has(a.id) }">{{ a.id }}</span>
          <small>{{ a.ready ? '출고 가능' : a.condAt ? `${time(a.condAt)} 이후` : a.where }}</small>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.inv { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-m); padding: 14px 16px; display: grid; gap: 10px; }
header { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
header p { font-size: 13px; color: var(--ink-2); }
.item { display: grid; grid-template-columns: 210px 1fr; gap: 12px; align-items: center; padding-top: 10px; border-top: 1px solid var(--line-2); }
.name { display: grid; }
.name strong { font-size: 14px; font-weight: 600; }
.name span { font-size: 12.5px; color: var(--ink-3); }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px 14px; }
li { display: grid; gap: 2px; justify-items: start; }
li small { font-size: 11.5px; color: var(--ink-3); white-space: nowrap; }
@media (max-width: 720px) { .item { grid-template-columns: 1fr; } }
</style>
