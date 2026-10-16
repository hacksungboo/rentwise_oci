<script setup lang="ts">
import { ref } from 'vue'
import { api, ApiError, type User } from '../api'

const emit = defineEmits<{ (e: 'login', user: User): void }>()
const username = ref('admin')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const r = await api.login(username.value, password.value)
    emit('login', r.user)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '서버에 연결하지 못했습니다.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login">
    <section class="card">
      <div class="brand">
        <svg width="34" height="34" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#18223A"/><rect x="7" y="9" width="18" height="5" rx="2" fill="#F4C542"/><rect x="7" y="18" width="11" height="5" rx="2" fill="#7FD1C8"/></svg>
        <div>
          <h1>rentwise</h1>
          <p>장비 렌탈 운영 보드</p>
        </div>
      </div>
      <form @submit.prevent="submit">
        <label class="field"><span>아이디</span><input v-model="username" type="text" autocomplete="username" /></label>
        <label class="field"><span>비밀번호</span><input v-model="password" type="password" autocomplete="current-password" /></label>
        <div v-if="error" class="banner error">{{ error }}</div>
        <button class="btn primary" :disabled="busy || !username || !password">로그인</button>
      </form>
      <p class="hint">시연 계정: 운영 책임자 <b>admin</b>, 현장 직원 <b>e1</b>~<b>e3</b></p>
    </section>
  </main>
</template>

<style scoped>
.login { min-height: 100vh; display: grid; place-items: center; padding: 24px; }
.card { width: min(380px, 100%); background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-m); padding: 28px; display: grid; gap: 22px; }
.brand { display: flex; gap: 12px; align-items: center; }
.brand h1 { font-size: 22px; font-weight: 700; letter-spacing: -.01em; }
.brand p { color: var(--ink-3); font-size: 13.5px; }
form { display: grid; gap: 14px; }
form .btn { height: 42px; }
.hint { font-size: 13px; color: var(--ink-3); }
</style>
