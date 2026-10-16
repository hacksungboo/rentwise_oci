<script setup lang="ts">
// 24시간제 날짜·시각 선택: 날짜 / 시(00~23) / 분(5분 단위). 값은 +09:00 ISO 문자열.
import { computed } from 'vue'
import { toLocalInput } from '../format'

const props = defineProps<{ modelValue: string | null; days: string[]; label: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string | null): void }>()

const hours = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const minutes = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0'))
const wd = ['일', '월', '화', '수', '목', '금', '토']

const parts = computed(() => {
  const v = toLocalInput(props.modelValue) // YYYY-MM-DDTHH:MM (KST)
  return v ? { date: v.slice(0, 10), hour: v.slice(11, 13), minute: v.slice(14, 16) } : { date: '', hour: '', minute: '' }
})
// 5분 단위가 아닌 값이 들어와도 그대로 보여주기
const minuteOptions = computed(() =>
  parts.value.minute && !minutes.includes(parts.value.minute) ? [...minutes, parts.value.minute].sort() : minutes,
)
const dayOptions = computed(() =>
  parts.value.date && !props.days.includes(parts.value.date) ? [parts.value.date, ...props.days] : props.days,
)

function dayLabel(d: string) {
  const dt = new Date(`${d}T12:00:00+09:00`)
  return `${Number(d.slice(5, 7))}월 ${Number(d.slice(8, 10))}일 (${wd[dt.getUTCDay()]})`
}

function update(field: 'date' | 'hour' | 'minute', value: string) {
  const p = { ...parts.value, [field]: value }
  if (!p.date) p.date = props.days[0] ?? ''
  if (!p.hour) p.hour = '09'
  if (!p.minute) p.minute = '00'
  emit('update:modelValue', p.date ? `${p.date}T${p.hour}:${p.minute}:00+09:00` : null)
}
</script>

<template>
  <fieldset class="tf" :class="{ empty: !modelValue }">
    <legend>{{ label }}</legend>
    <select :value="parts.date" :aria-label="`${label} 날짜`" @change="update('date', ($event.target as HTMLSelectElement).value)">
      <option value="" disabled>날짜</option>
      <option v-for="d in dayOptions" :key="d" :value="d">{{ dayLabel(d) }}</option>
    </select>
    <div class="hm">
      <select class="num" :value="parts.hour" :aria-label="`${label} 시`" @change="update('hour', ($event.target as HTMLSelectElement).value)">
        <option value="" disabled>시</option>
        <option v-for="h in hours" :key="h" :value="h">{{ h }}</option>
      </select>
      <span aria-hidden="true">:</span>
      <select class="num" :value="parts.minute" :aria-label="`${label} 분`" @change="update('minute', ($event.target as HTMLSelectElement).value)">
        <option value="" disabled>분</option>
        <option v-for="m in minuteOptions" :key="m" :value="m">{{ m }}</option>
      </select>
    </div>
  </fieldset>
</template>

<style scoped>
.tf { border: 0; margin: 0; padding: 0; display: grid; gap: 4px; min-width: 0; }
legend { font-size: 13px; color: var(--ink-2); padding: 0; margin-bottom: 4px; }
.hm { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 4px; }
.hm span { font-weight: 600; color: var(--ink-2); }
select { min-width: 0; }
.tf.empty select { color: var(--ink-3); }
</style>
