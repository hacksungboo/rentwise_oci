<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { api, ApiError, type CustomerMessage } from '../api'

const props = defineProps<{ planId: string; stateRevision: number }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const message = ref<CustomerMessage | null>(null)
const error = ref('')
const busy = ref(false)
const copied = ref(false)
let generation = 0
onUnmounted(() => { generation++ })

async function load(copy = false) {
  const request = ++generation
  message.value = null; error.value = ''; copied.value = false; busy.value = true
  try {
    const result = await api.customerMessage(props.planId)
    if (request !== generation) return
    message.value = result
    if (copy) {
      await navigator.clipboard.writeText(result.text)
      if (request === generation) copied.value = true
    }
  } catch (e) {
    if (request === generation) error.value = e instanceof ApiError ? e.message : '복사할 수 없습니다. 아래 안내문을 직접 선택해 복사해 주세요.'
  } finally { if (request === generation) busy.value = false }
}
watch(() => [props.planId, props.stateRevision], () => load(), { immediate: true })
</script>

<template>
  <section class="customer-message" aria-label="고객 안내문">
    <div class="row"><h3>고객에게 보낼 안내문</h3><button class="btn ghost small" @click="emit('close')">닫기</button></div>
    <p v-if="busy" aria-live="polite">현재 확정 일정을 확인하고 있습니다…</p>
    <template v-if="message">
      <p><strong>{{ message.recipient.name }}</strong> · {{ message.requires_dispatch ? '업체 확인 필요' : '일정 배정 완료' }}</p>
      <textarea :value="message.text" readonly aria-label="고객 안내문 내용" rows="8" />
      <p class="note">{{ message.notice }}</p>
      <button class="btn primary" :disabled="busy" @click="load(true)">{{ copied ? '복사 완료' : '최신 일정 확인하고 복사' }}</button>
    </template>
    <p v-if="error" class="banner error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.customer-message { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-m); padding: 16px; margin-bottom: 12px; display: grid; gap: 10px; font-size: 13px; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
h3, p { margin: 0; }
h3 { font-size: 15px; }
textarea { width: 100%; resize: vertical; line-height: 1.7; font: inherit; white-space: pre-wrap; }
.note { color: var(--ink-3); font-size: 12px; line-height: 1.6; }
</style>
