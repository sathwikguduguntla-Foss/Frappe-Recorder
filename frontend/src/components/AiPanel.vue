<template>
  <section v-if="visible" class="mt-6 rounded-xl border border-outline-gray-2 bg-surface-base" aria-label="Transcript and AI notes">
    <div class="flex flex-wrap items-center gap-1 border-b border-outline-gray-1 px-3 pt-2" role="tablist">
      <button
        v-for="t in tabs"
        :key="t.id"
        type="button"
        role="tab"
        :aria-selected="tab === t.id"
        class="-mb-px border-b-2 px-3 py-2 text-base"
        :class="tab === t.id ? 'border-ink-green-6 font-medium text-ink-gray-9' : 'border-transparent text-ink-gray-5 hover:text-ink-gray-8'"
        @click="tab = t.id"
      >
        {{ t.label }}
      </button>
    </div>

    <!-- Work running in this browser -->
    <div v-if="job" class="flex items-start gap-3 border-b border-outline-gray-1 p-4" role="status">
      <LoadingIndicator class="mt-0.5 size-5 shrink-0 text-ink-green-6" />
      <div class="min-w-0 flex-1">
        <p class="text-base font-medium text-ink-gray-9">{{ jobTitle }}</p>
        <p class="mt-0.5 text-sm text-ink-gray-6">{{ jobDetail }}</p>
        <div class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-gray-2">
          <div class="h-full rounded-full bg-surface-green-6 transition-all" :style="{ width: `${Math.round((job.value || 0) * 100)}%` }" />
        </div>
        <p class="mt-1.5 text-xs text-ink-gray-5">Running on this device · {{ elapsedText }} elapsed. Keep this page open.</p>
      </div>
    </div>

    <p v-if="error" role="alert" class="border-b border-outline-gray-1 bg-surface-red-1 px-4 py-2 text-sm text-ink-red-7">{{ error }}</p>

    <div v-if="canWriteHere && !llmCached" class="flex flex-wrap items-center gap-3 border-b border-outline-gray-1 px-4 py-3">
      <Button label="Download writing model" :disabled="!!job" @click="downloadWritingModel" />
      <p class="text-sm text-ink-gray-6">The first download uses about 1 GB. This browser can reuse it for other recordings.</p>
    </div>

    <div class="p-4" @click="onContentClick">
      <!-- Assistant -->
      <template v-if="tab === 'assistant'">
        <div v-if="ai.insights_status === 'Ready'" class="text-base leading-relaxed text-ink-gray-8" v-html="summaryHtml" />
        <StepState v-else kind="insights" />

        <div v-if="ai.questions.length && canAsk" class="mt-4 flex flex-col gap-2">
          <button
            v-for="q in ai.questions"
            :key="q"
            type="button"
            class="rounded-lg border border-outline-gray-2 px-3 py-2 text-left text-sm text-ink-gray-7 hover:bg-surface-gray-2"
            :disabled="!!job"
            @click="ask(q)"
          >
            {{ q }}
          </button>
        </div>

        <div v-for="(item, i) in chat" :key="i" class="mt-4">
          <p class="text-sm font-medium text-ink-gray-9">{{ item.question }}</p>
          <p v-if="item.pending" class="mt-1 text-sm text-ink-gray-5">Thinking…</p>
          <div v-else class="mt-1 text-sm leading-relaxed text-ink-gray-8" v-html="render(item.answer)" />
        </div>

        <form v-if="canAsk" class="mt-4 flex gap-2" @submit.prevent="ask(question)">
          <input
            v-model="question"
            :disabled="!!job"
            aria-label="Ask anything about this video"
            placeholder="Ask anything about this video…"
            maxlength="500"
            class="form-input min-w-0 flex-1 rounded-full border-outline-gray-2 bg-surface-gray-2 px-4 py-2 text-base placeholder:text-ink-gray-4"
          />
          <Button type="submit" variant="solid" icon="lucide-arrow-up" aria-label="Ask" :disabled="!question.trim() || !!job" />
        </form>
      </template>

      <!-- Highlights -->
      <template v-else-if="tab === 'highlights'">
        <ul v-if="ai.highlights.length" class="flex flex-col">
          <li v-for="h in ai.highlights" :key="h.time">
            <button type="button" class="flex w-full items-baseline gap-3 rounded-lg px-2 py-2 text-left hover:bg-surface-gray-2" @click="$emit('seek', h.time)">
              <span class="w-12 shrink-0 text-sm font-medium tabular-nums text-ink-green-7">{{ formatTime(h.time) }}</span>
              <span class="text-base text-ink-gray-8">{{ h.title }}</span>
            </button>
          </li>
        </ul>
        <StepState v-else kind="insights" />
      </template>

      <!-- Transcript -->
      <template v-else-if="tab === 'transcript'">
        <template v-if="ai.transcript.length">
          <div class="mb-2 flex justify-end">
            <Button size="sm" icon-left="lucide-copy" label="Copy" @click="copyTranscript" />
          </div>
          <ol class="flex max-h-[28rem] flex-col overflow-y-auto">
            <li v-for="(s, i) in ai.transcript" :key="i">
              <button
                type="button"
                class="flex w-full items-baseline gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-surface-gray-2"
                :class="{ 'bg-surface-gray-2': i === activeSegment }"
                @click="$emit('seek', s.start)"
              >
                <span class="w-12 shrink-0 text-sm font-medium tabular-nums text-ink-green-7">{{ formatTime(s.start) }}</span>
                <span class="text-base text-ink-gray-8">{{ s.text }}</span>
              </button>
            </li>
          </ol>
          <div v-if="recording.is_owner" class="mt-3 border-t border-outline-gray-1 pt-3 text-right">
            <Button size="sm" variant="ghost" label="Transcribe again" :disabled="!!job" @click="redo" />
          </div>
        </template>
        <StepState v-else kind="transcript" />
      </template>

      <!-- SOP -->
      <template v-else-if="tab === 'sop'">
        <template v-if="ai.sop_status === 'Ready'">
          <div class="text-base leading-relaxed text-ink-gray-8" v-html="sopHtml" />
          <div class="mt-4 flex gap-2 border-t border-outline-gray-1 pt-3">
            <Button size="sm" icon-left="lucide-copy" label="Copy" @click="copyText(ai.sop)" />
            <Button v-if="recording.is_owner" size="sm" variant="ghost" label="Write again" :disabled="!!job || !canWriteHere" @click="runSop" />
          </div>
        </template>
        <StepState v-else kind="sop" />
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button, LoadingIndicator, toast } from 'frappe-ui'
import { api, copyText, errorMessage } from '@/api'
import { renderMarkdown } from '@/ai/markdown'
import * as engine from '@/ai/engine'

const props = defineProps({
  recording: { type: Object, required: true },
  currentTime: { type: Number, default: 0 },
})
const emit = defineEmits(['seek'])

const token = props.recording.token
const config = ref(null)
const capability = ref({ webgpu: false, f16: false })
const llmCached = ref(false)
const ai = ref(emptyAi())
const tab = ref('assistant')
const job = ref(null)
const error = ref('')
const question = ref('')
const chat = ref([])
const now = ref(Date.now())

let clock = null

function emptyAi() {
  return { transcript_status: 'Not Started', transcript: [], insights_status: 'Not Started', summary: '', highlights: [], questions: [], sop_status: 'Not Started', sop: '' }
}

const tabs = [
  { id: 'assistant', label: 'Assistant' },
  { id: 'highlights', label: 'Highlights' },
  { id: 'transcript', label: 'Transcript' },
  { id: 'sop', label: 'SOP' },
]

const formatTime = engine.formatTime
const render = renderMarkdown
const summaryHtml = computed(() => renderMarkdown(ai.value.summary))
const sopHtml = computed(() => renderMarkdown(ai.value.sop))

const hasAnything = computed(() => ai.value.transcript.length || ai.value.summary || ai.value.sop)
// Viewers see the panel once there is something to read; owners always (when enabled).
const visible = computed(() => config.value?.enabled && props.recording.status === 'Ready' && (props.recording.is_owner || hasAnything.value))
const canWriteHere = computed(() => props.recording.is_owner && capability.value.webgpu)
const canAsk = computed(() => ai.value.transcript.length && canWriteHere.value)

const activeSegment = computed(() => {
  const t = props.currentTime
  let index = -1
  ai.value.transcript.forEach((s, i) => {
    if (s.start <= t) index = i
  })
  return index
})

const elapsedText = computed(() => engine.formatTime(job.value ? (now.value - job.value.startedAt) / 1000 : 0))

const jobTitle = computed(() => {
  const j = job.value
  if (!j) return ''
  if (j.stage === 'download' || j.kind === 'model') {
    return j.kind === 'transcript' ? 'Loading the speech model' : 'Loading the writing model'
  }
  return {
    transcript: 'Creating your transcript',
    insights: 'Writing the summary and highlights',
    sop: 'Creating your SOP',
    ask: 'Thinking about your question',
  }[j.kind]
})

const jobDetail = computed(() => {
  const j = job.value
  if (!j) return ''
  return {
    fetch: 'Loading the video',
    decode: 'Reading the sound',
    download: j.text || 'Checking the browser cache and downloading any missing files.',
    transcribe: 'Listening to the recording',
    write: 'Reading your transcript and video timeline',
  }[j.stage] || ''
})

// ---------------------------------------------------------------- loading

async function refresh() {
  ai.value = { ...emptyAi(), ...(await api.getAi(token)) }
}

onMounted(async () => {
  try {
    config.value = await api.getAiConfig()
    if (!config.value.enabled || props.recording.status !== 'Ready') return
    capability.value = await engine.getCapability()
    await refresh()
    if (props.recording.is_owner) {
      if (canWriteHere.value) llmCached.value = await engine.isLlmCached(config.value.llm_model)
      autoRun()
    }
  } catch (e) {
    error.value = errorMessage(e)
  }
})

// The transcript starts by itself for the owner; the summary too when its model is
// already on this device. Otherwise the owner chooses to start it,
// since the first download is large.
async function autoRun() {
  if (ai.value.transcript_status === 'Not Started') await runTranscript()
  if (ai.value.transcript_status !== 'Ready' || ai.value.insights_status !== 'Not Started') return
  if (canWriteHere.value && llmCached.value) await runInsights()
}

// ---------------------------------------------------------------- steps

function startJob(kind) {
  job.value = { kind, stage: 'start', value: 0, startedAt: Date.now() }
  error.value = ''
  clock = setInterval(() => (now.value = Date.now()), 1000)
}

function onProgress(p) {
  if (job.value) Object.assign(job.value, { stage: p.stage, value: p.value ?? job.value.value, text: p.text })
}

function endJob() {
  job.value = null
  clearInterval(clock)
}

async function fail(kind, e) {
  error.value = errorMessage(e)
  try {
    ai.value = { ...emptyAi(), ...(await api.reportAiFailure(token, kind, error.value)) }
  } catch (err) {
    /* the message is already on screen */
  }
}

async function runTranscript() {
  startJob('transcript')
  try {
    const segments = await engine.transcribe(props.recording.stream_url, config.value.whisper_model, onProgress)
    if (!segments.length) throw new Error('No speech was found in this recording.')
    ai.value = { ...emptyAi(), ...(await api.saveTranscript(token, segments, config.value.whisper_model)) }
    tab.value = 'transcript'
  } catch (e) {
    await fail('transcript', e)
  } finally {
    endJob()
  }
}

async function downloadWritingModel() {
  if (job.value || !canWriteHere.value || llmCached.value) return
  startJob('model')
  try {
    await engine.downloadWritingModel(config.value.llm_model, onProgress)
    llmCached.value = true
    toast.success('Writing model is ready')
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    endJob()
  }
}

async function runInsights() {
  startJob('insights')
  try {
    const data = await engine.writeInsights(config.value, ai.value.transcript, onProgress)
    ai.value = { ...emptyAi(), ...(await api.saveInsights(token, data, await engine.resolveLlmModel(config.value.llm_model))) }
    llmCached.value = true
    tab.value = 'assistant'
  } catch (e) {
    await fail('insights', e)
  } finally {
    endJob()
  }
}

async function runSop() {
  startJob('sop')
  try {
    const sop = await engine.writeSop(config.value, ai.value.transcript, onProgress)
    ai.value = { ...emptyAi(), ...(await api.saveSop(token, sop, await engine.resolveLlmModel(config.value.llm_model))) }
    llmCached.value = true
  } catch (e) {
    await fail('sop', e)
  } finally {
    endJob()
  }
}

async function ask(text) {
  text = (text || '').trim()
  if (!text || job.value) return
  question.value = ''
  const item = { question: text, answer: '', pending: true }
  chat.value.push(item)
  try {
    startJob('ask')
    item.answer = await engine.answer(config.value, ai.value.transcript, text, onProgress)
    llmCached.value = true
  } catch (e) {
    item.answer = errorMessage(e)
  } finally {
    item.pending = false
    endJob()
  }
}

async function redo() {
  ai.value = { ...emptyAi(), ...(await api.resetAi(token)) }
  chat.value = []
  await autoRun()
}

async function copyTranscript() {
  const text = engine.lines(ai.value.transcript).join('\n')
  if (await copyText(text)) toast.success('Transcript copied')
}

// Times inside the summary and SOP are rendered as buttons with data-time.
function onContentClick(event) {
  const target = event.target.closest?.('[data-time]')
  if (target) emit('seek', Number(target.dataset.time))
}

function warnBeforeLeaving(event) {
  if (!job.value) return
  event.preventDefault()
  event.returnValue = ''
}
window.addEventListener('beforeunload', warnBeforeLeaving)

onBeforeUnmount(() => {
  clearInterval(clock)
  window.removeEventListener('beforeunload', warnBeforeLeaving)
})

// ---------------------------------------------------------------- empty / waiting states

const STEP_COPY = {
  transcript: { field: 'transcript_status', none: 'No transcript yet.' },
  insights: { field: 'insights_status', none: 'No summary yet.' },
  sop: { field: 'sop_status', none: 'No SOP yet.' },
}

/** What a tab shows before its content exists: progress, a start button, or why it can't run here. */
const StepState = defineComponent({
  props: { kind: { type: String, required: true } },
  setup(stepProps) {
    return () => {
      const step = STEP_COPY[stepProps.kind]
      const status = ai.value[step.field]
      const owner = props.recording.is_owner
      const p = (text, cls = 'text-base text-ink-gray-6') => h('p', { class: cls }, text)

      if (job.value) return p('Working on it…')
      if (stepProps.kind !== 'transcript' && ai.value.transcript_status !== 'Ready') {
        return p(owner ? 'The transcript comes first.' : step.none)
      }
      if (!owner) return p(step.none)

      if (stepProps.kind === 'transcript') {
        return h('div', { class: 'flex flex-col items-start gap-3' }, [
          status === 'Failed' ? p(ai.value.ai_error || 'The transcript could not be made.', 'text-base text-ink-red-7') : p('Make a transcript of this video on this device.'),
          h(Button, { variant: 'solid', label: status === 'Failed' ? 'Try again' : 'Create transcript', onClick: runTranscript }),
        ])
      }

      if (!canWriteHere.value) {
        return p(
          'This device can’t run the writing model: it needs a browser with WebGPU (Chrome or Edge on a computer with a graphics card). Open this page there.',
        )
      }
      const label = stepProps.kind === 'sop' ? 'Create SOP' : 'Write summary'
      return h('div', { class: 'flex flex-col items-start gap-3' }, [
        status === 'Failed' && (!error.value || ai.value.ai_error !== error.value)
          ? p(ai.value.ai_error || 'That did not work.', 'text-base text-ink-red-7')
          : null,
        h(Button, {
          variant: 'solid',
          iconLeft: 'lucide-sparkles',
          label: status === 'Failed' ? 'Try again' : label,
          onClick: stepProps.kind === 'sop' ? runSop : runInsights,
        }),
      ])
    }
  },
})
</script>
