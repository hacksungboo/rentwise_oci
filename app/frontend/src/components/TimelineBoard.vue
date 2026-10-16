<script setup lang="ts">
import { computed } from 'vue'
import type { Card, Lane } from '../api'
import { KIND_LABEL, minuteOfDay, time } from '../format'

export interface Ghost { job_id: string; lane: string; start_at: string; end_at: string; kind: string }

const props = defineProps<{
  lanes: Lane[]
  prep: Card[]
  ghosts?: Ghost[]
  changed?: Set<string>
  preferred?: Record<string, string>  // job_id → 원래 담당 직원 이름 (표시용)
}>()
const emit = defineEmits<{ (e: 'select-asset', id: string): void }>()

const START = 8 * 60 + 30
const END = 18 * 60 + 30
const SPAN = END - START
const hours = Array.from({ length: 10 }, (_, i) => 9 + i)

const pct = (m: number) => `${Math.max(0, Math.min(100, ((m - START) / SPAN) * 100))}%`
const width = (a: string, b: string) => `${Math.max(0.6, ((minuteOfDay(b) - minuteOfDay(a)) / SPAN) * 100)}%`
const left = (a: string) => pct(minuteOfDay(a))

const rows = computed(() => [
  ...props.lanes.map((l) => ({ id: l.id, name: l.name, sub: l.id, items: l.items, breaks: l.breaks, shift: l.shift })),
  { id: 'PREP', name: '창고 준비', sub: '세척·점검', items: props.prep, breaks: [], shift: null },
])
const ghostsIn = (lane: string) => (props.ghosts ?? []).filter((g) => g.lane === lane)
const isChanged = (id: string) => props.changed?.has(id) ?? false

function siteOf(c: Card) {
  return c.kind === 'PREP' ? '' : c.site_name ?? ''
}
function serviceStart(c: Card) {
  return c.segments.find((s) => s.kind === 'SERVICE' || s.kind === 'PREP')?.start_at ?? c.start_at
}
// 카드 안에서 구간 위치 (카드 폭 기준 %)
function segStyle(c: Card, s: { start_at: string; end_at: string }) {
  const total = minuteOfDay(c.end_at) - minuteOfDay(c.start_at) || 1
  return {
    left: `${((minuteOfDay(s.start_at) - minuteOfDay(c.start_at)) / total) * 100}%`,
    width: `${Math.max(2, ((minuteOfDay(s.end_at) - minuteOfDay(s.start_at)) / total) * 100)}%`,
  }
}
</script>

<template>
  <div class="board" role="table" aria-label="직원별 하루 일정">
    <div class="axis" role="row">
      <div class="lane-name" />
      <div class="track">
        <span v-for="h in hours" :key="h" class="hour num" :style="{ left: pct(h * 60) }">{{ h }}시</span>
      </div>
    </div>

    <div v-for="r in rows" :key="r.id" class="row" :class="{ prep: r.id === 'PREP' }" role="row">
      <div class="lane-name">
        <strong>{{ r.name }}</strong>
        <span>{{ r.sub }}</span>
      </div>
      <div class="track">
        <span v-for="h in hours" :key="h" class="grid" :style="{ left: pct(h * 60) }" />
        <span v-if="r.shift" class="off" :style="{ left: '0', width: pct(minuteOfDay(r.shift[0])) }" />
        <span v-if="r.shift" class="off" :style="{ left: pct(minuteOfDay(r.shift[1])), right: '0' }" />
        <span v-for="(b, i) in r.breaks" :key="i" class="break" :style="{ left: left(b.start_at), width: width(b.start_at, b.end_at) }"
              :title="`휴식 ${time(b.start_at)}~${time(b.end_at)}`"><em>휴식</em></span>

        <div v-for="g in ghostsIn(r.id)" :key="'g' + g.job_id" class="ghost" :class="'k-' + g.kind"
             :style="{ left: left(g.start_at), width: width(g.start_at, g.end_at) }">
          <span>기존 {{ time(g.start_at) }}</span>
        </div>

        <Transition v-for="c in r.items" :key="c.job_id" appear name="land">
          <div class="card" :class="['k-' + c.kind, { changed: isChanged(c.job_id) }]"
               :style="{ left: left(c.start_at), width: width(c.start_at, c.end_at) }"
               :title="`${KIND_LABEL[c.kind]} ${siteOf(c)} ${time(c.start_at)}~${time(c.end_at)}`">
            <div class="label">
              <span class="kind">{{ KIND_LABEL[c.kind] }}</span>
              <span class="site">{{ siteOf(c) }}</span>
            </div>
            <div class="meta">
              <span class="num">{{ time(serviceStart(c)) }}</span>
              <button v-for="a in c.asset_ids" :key="a" class="asset-tag" type="button"
                      @click="emit('select-asset', a)">{{ a }}</button>
            </div>
            <div class="bar">
              <span v-for="(s, i) in c.segments" :key="i" class="seg" :class="s.kind.toLowerCase()" :style="segStyle(c, s)" />
            </div>
          </div>
        </Transition>
      </div>
    </div>

    <div class="legend">
      <span><i class="kind-dot k-DELIVERY" />납품</span>
      <span><i class="kind-dot k-PICKUP" />회수</span>
      <span><i class="kind-dot k-AS" />A/S</span>
      <span><i class="kind-dot k-TRANSFER" />고객 간 이동</span>
      <span><i class="line" />이동</span>
      <span><i class="ghost-key" />변경 전 위치</span>
    </div>
  </div>
</template>

<style scoped>
.board { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-m); padding: 6px 0 12px; overflow-x: auto; }
.axis, .row { display: grid; grid-template-columns: 116px 1fr; min-width: 760px; }
.axis .track { height: 26px; }
.hour { position: absolute; top: 4px; transform: translateX(-50%); font-size: 12px; color: var(--ink-3); }
.row { border-top: 1px solid var(--line-2); }
.row.prep { background: #fafbfc; }
.lane-name { padding: 12px 14px; display: grid; align-content: center; gap: 1px; border-right: 1px solid var(--line-2); }
.lane-name strong { font-size: 14.5px; font-weight: 600; }
.lane-name span { font-size: 12px; color: var(--ink-3); }
.track { position: relative; height: 74px; margin: 0 14px; }
.grid { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--line-2); }
.off { position: absolute; top: 0; bottom: 0; background: repeating-linear-gradient(135deg, transparent 0 6px, #eef0f4 6px 7px); }
.break { position: absolute; top: 6px; bottom: 6px; border-radius: 6px; background: repeating-linear-gradient(135deg, #f1f3f7 0 5px, #e3e7ee 5px 7px); display: grid; place-items: end center; }
.break em { font-style: normal; font-size: 11px; color: var(--ink-3); padding-bottom: 3px; }

.card {
  position: absolute; top: 7px; bottom: 7px; min-width: 64px;
  background: color-mix(in srgb, var(--k) 9%, white); border: 1px solid color-mix(in srgb, var(--k) 35%, white);
  border-radius: 8px; padding: 5px 7px 0; display: grid; grid-template-rows: auto auto 1fr; overflow: hidden;
}
.card .label { display: flex; gap: 5px; align-items: baseline; white-space: nowrap; overflow: hidden; }
.card .kind { font-size: 12px; font-weight: 700; color: var(--k); }
.card .site { font-size: 12.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; }
.card .meta { display: flex; gap: 5px; align-items: center; font-size: 12px; color: var(--ink-2); white-space: nowrap; }
.card .asset-tag { height: 18px; font-size: 11px; padding: 0 5px; border: 0; cursor: pointer; }
.bar { position: relative; align-self: end; height: 12px; margin: 0 -7px; }
.seg { position: absolute; top: 50%; transform: translateY(-50%); }
.seg.travel { height: 2px; background: color-mix(in srgb, var(--k) 45%, white); }
.seg.service { height: 8px; border-radius: 3px; background: var(--k); }
.seg.prep { height: 8px; border-radius: 3px; background: repeating-linear-gradient(135deg, var(--prep) 0 4px, #c7ccd6 4px 7px); }

.card.changed { border: 2px solid var(--ink); box-shadow: 0 0 0 4px color-mix(in srgb, var(--tag) 55%, transparent); z-index: 2; }
.ghost { position: absolute; top: 7px; bottom: 7px; border: 1.5px dashed color-mix(in srgb, var(--k) 70%, white); border-radius: 8px; display: grid; align-content: start; padding: 4px 6px; }
.ghost span { font-size: 11.5px; color: var(--ink-3); white-space: nowrap; }

/* 변경안이 보드에 처음 올라올 때 한 번만 */
.land-enter-active { transition: transform .45s cubic-bezier(.2, .8, .2, 1), opacity .45s; }
.land-enter-from { opacity: 0; transform: translateY(-10px) scale(.97); }

.legend { display: flex; flex-wrap: wrap; gap: 16px; padding: 10px 14px 0 130px; font-size: 12.5px; color: var(--ink-2); }
.legend span { display: inline-flex; gap: 6px; align-items: center; }
.legend .line { width: 18px; height: 2px; background: var(--ink-3); display: inline-block; }
.legend .ghost-key { width: 18px; height: 12px; border: 1.5px dashed var(--ink-3); border-radius: 3px; display: inline-block; }
</style>
