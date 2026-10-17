<script setup lang="ts">
import { computed } from 'vue'
import { blocks } from '../markdown'

const props = defineProps<{ text: string }>()
const content = computed(() => blocks(props.text))
</script>

<template>
  <div class="markdown">
    <template v-for="(block, b) in content" :key="b">
      <h4 v-if="block.kind === 'heading'"><template v-for="(part, i) in block.lines[0]" :key="i"><strong v-if="part.strong">{{ part.text }}</strong><template v-else>{{ part.text }}</template></template></h4>
      <ul v-else-if="block.kind === 'list'">
        <li v-for="(line, l) in block.lines" :key="l"><template v-for="(part, i) in line" :key="i"><strong v-if="part.strong">{{ part.text }}</strong><template v-else>{{ part.text }}</template></template></li>
      </ul>
      <blockquote v-else-if="block.kind === 'quote'">
        <p v-for="(line, l) in block.lines" :key="l"><template v-for="(part, i) in line" :key="i"><strong v-if="part.strong">{{ part.text }}</strong><template v-else>{{ part.text }}</template></template></p>
      </blockquote>
      <div v-else><p v-for="(line, l) in block.lines" :key="l"><template v-for="(part, i) in line" :key="i"><strong v-if="part.strong">{{ part.text }}</strong><template v-else>{{ part.text }}</template></template></p></div>
    </template>
  </div>
</template>

<style scoped>
.markdown { display: grid; gap: 12px; font-size: 13.5px; line-height: 1.7; overflow-wrap: anywhere; }
h4 { margin: 6px 0 -5px; font-size: 13px; color: var(--ink-2); }
ul { margin: 0; padding-left: 19px; display: grid; gap: 8px; }
li::marker { color: var(--ok, #158558); }
strong { font-weight: 750; color: var(--ink); background: color-mix(in srgb, var(--tag, #f4c542) 19%, transparent); border-radius: 3px; padding: 0 2px; }
blockquote { margin: 2px 0 0; padding: 8px 11px; border-left: 3px solid var(--ok, #158558); background: var(--surface); font-size: 12px; color: var(--ink-2); }
blockquote strong { background: transparent; padding: 0; }
p { margin: 0; }
</style>
