<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type SystemInfo } from '../api'

const emit = defineEmits<{ (e: 'close'): void }>()
const info = ref<SystemInfo | null>(null)
const error = ref('')

onMounted(async () => {
  try {
    info.value = await api.system()
  } catch {
    error.value = '실행 환경 정보를 불러오지 못했습니다.'
  }
})

function uptime(s: number) {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h}시간 ${m}분` : `${m}분`
}
</script>

<template>
  <div class="scrim" @click.self="emit('close')">
    <aside class="sheet" role="dialog" aria-label="실행 환경">
      <header>
        <h2>실행 환경</h2>
        <button class="btn ghost small" @click="emit('close')">닫기</button>
      </header>
      <p class="lead">아래 값은 서버가 OCI 인스턴스 메타데이터 서비스에서 직접 읽은 값입니다. 메타데이터 주소(169.254.169.254)는 OCI 인스턴스 안에서만 응답합니다.</p>

      <div v-if="error" class="banner error">{{ error }}</div>
      <template v-if="info">
        <section>
          <h3><span class="dot" :class="info.cloud.provider" />{{ info.cloud.provider === 'oci' ? 'Oracle Cloud Infrastructure' : '로컬 실행' }}</h3>
          <dl class="num">
            <dt>리전</dt><dd>{{ info.cloud.region ?? '—' }}</dd>
            <dt>가용 도메인</dt><dd>{{ info.cloud.availability_domain ?? '—' }}</dd>
            <dt>장애 도메인</dt><dd>{{ info.cloud.fault_domain ?? '—' }}</dd>
            <dt>인스턴스</dt><dd>{{ info.cloud.display_name ?? '—' }}</dd>
            <dt>Shape</dt><dd>{{ info.cloud.shape ?? '—' }}<template v-if="info.cloud.ocpus"> · {{ info.cloud.ocpus }} OCPU · {{ info.cloud.memory_gb }} GB</template></dd>
            <dt>사설 IP</dt><dd>{{ info.cloud.private_ip ?? '—' }}</dd>
            <dt>인스턴스 OCID</dt><dd class="mono">{{ info.cloud.instance_id ?? '—' }}</dd>
            <dt>실행 시간</dt><dd>{{ uptime(info.cloud.uptime_s) }}</dd>
          </dl>
        </section>
        <section>
          <h3>데이터베이스</h3>
          <dl>
            <dt>제품</dt><dd>{{ info.db.banner ?? info.db.dialect }}</dd>
            <dt>PDB</dt><dd>{{ info.db.pdb ?? '—' }}</dd>
            <dt>DB 호스트</dt><dd>{{ info.db.server_host ?? '—' }}</dd>
          </dl>
        </section>
        <section>
          <h3>배포</h3>
          <dl class="num">
            <dt>커밋</dt><dd class="mono">{{ info.build.sha }}</dd>
            <dt>계산 엔진</dt><dd>{{ info.build.engine_mode === 'real' ? 'AI 배정 엔진' : '고정 응답 엔진' }}</dd>
            <dt>경로</dt><dd>브라우저 → Cloudflare → 터널 → nginx → FastAPI → Oracle</dd>
          </dl>
        </section>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.scrim { position: fixed; inset: 0; background: rgba(24, 34, 58, .28); z-index: 40; display: flex; justify-content: flex-end; }
.sheet { width: min(460px, 100%); height: 100%; overflow-y: auto; background: var(--surface); padding: 20px 22px; display: grid; gap: 18px; align-content: start; box-shadow: -12px 0 32px rgba(24, 34, 58, .18); }
header { display: flex; justify-content: space-between; align-items: center; }
.lead { font-size: 13.5px; color: var(--ink-2); }
section { display: grid; gap: 8px; border-top: 1px solid var(--line-2); padding-top: 14px; }
h3 { display: flex; align-items: center; gap: 8px; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--ink-3); }
.dot.oci { background: #c74634; }
dl { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 6px 12px; margin: 0; font-size: 13.5px; }
dt { color: var(--ink-3); }
dd { margin: 0; overflow-wrap: anywhere; }
.mono { font-size: 12px; }
</style>
