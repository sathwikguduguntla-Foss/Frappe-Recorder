// Runs the open-source models in this browser and turns their output into what the
// server stores. Nothing here needs an API key: models are downloaded once from
// Hugging Face, cached by the browser, and run on this device.
//
// The prompts come from the server (`get_ai_config`).

const SAMPLE_RATE = 16000
// The browser models read about 4,000 tokens at a time; leave room for the prompt and reply.
const PART_CHARS = 6000
const ASK_CHARS = 7000

// ---------------------------------------------------------------- device

let capabilityPromise = null

/** What this device can run: WebGPU makes both models much faster, and the writing model needs it. */
export function getCapability() {
  if (!capabilityPromise) {
    capabilityPromise = (async () => {
      try {
        const adapter = navigator.gpu && (await navigator.gpu.requestAdapter())
        return { webgpu: !!adapter, f16: !!adapter?.features?.has('shader-f16') }
      } catch (e) {
        return { webgpu: false, f16: false }
      }
    })()
  }
  return capabilityPromise
}

// ---------------------------------------------------------------- transcript

/**
 * Downloads the recording, decodes its sound and transcribes it.
 * onProgress({ stage: 'fetch' | 'decode' | 'download' | 'transcribe', value: 0..1 })
 */
export async function transcribe(videoUrl, model, onProgress = () => {}) {
  const { webgpu } = await getCapability()
  const audio = await loadAudio(videoUrl, onProgress)
  if (!audio.length) throw new Error('This recording has no sound to transcribe.')

  const worker = new Worker(new URL('./whisper.worker.js', import.meta.url), { type: 'module' })
  try {
    return await new Promise((resolve, reject) => {
      worker.onmessage = ({ data }) => {
        if (data.type === 'stage') onProgress({ stage: data.stage, value: 0 })
        else if (data.type === 'progress') onProgress({ stage: data.stage, value: data.value })
        else if (data.type === 'done') resolve(data.segments)
        else if (data.type === 'error') reject(friendlyError(data.message, 'speech'))
      }
      worker.onerror = (e) => reject(new Error(e.message || 'The speech model stopped unexpectedly.'))
      worker.postMessage({ type: 'transcribe', model, device: webgpu ? 'webgpu' : 'wasm', audio }, [audio.buffer])
    })
  } finally {
    worker.terminate()
  }
}

async function loadAudio(url, onProgress) {
  onProgress({ stage: 'fetch', value: 0 })
  const response = await fetch(url, { credentials: 'same-origin' })
  if (!response.ok) throw new Error(`Could not load the video (${response.status}).`)
  const bytes = await readWithProgress(response, (value) => onProgress({ stage: 'fetch', value }))

  onProgress({ stage: 'decode', value: 0 })
  // Asking for a 16 kHz context makes the browser resample to what Whisper expects.
  const context = new AudioContext({ sampleRate: SAMPLE_RATE })
  try {
    const decoded = await context.decodeAudioData(bytes.buffer)
    return mixToMono(decoded)
  } catch (e) {
    throw new Error('This browser could not read the sound in this recording.')
  } finally {
    context.close()
  }
}

async function readWithProgress(response, onProgress) {
  const total = Number(response.headers.get('Content-Length')) || 0
  if (!response.body || !total) return new Uint8Array(await response.arrayBuffer())
  const reader = response.body.getReader()
  const bytes = new Uint8Array(total)
  let received = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    bytes.set(value, received)
    received += value.length
    onProgress(received / total)
  }
  return bytes.subarray(0, received)
}

function mixToMono(buffer) {
  if (buffer.numberOfChannels === 1) return new Float32Array(buffer.getChannelData(0))
  const mono = new Float32Array(buffer.length)
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const data = buffer.getChannelData(c)
    for (let i = 0; i < data.length; i++) mono[i] += data[i] / buffer.numberOfChannels
  }
  return mono
}

// ---------------------------------------------------------------- writing model

let llm = null
let llmModel = ''

/** The model id this device can actually run (WebGPU without 16-bit support needs the f32 build). */
export async function resolveLlmModel(model) {
  const { f16 } = await getCapability()
  return f16 ? model : model.replace('q4f16_1', 'q4f32_1')
}

/** True when the writing model is already downloaded, so it can start without asking. */
export async function isLlmCached(model) {
  try {
    const webllm = await import('@mlc-ai/web-llm')
    return await webllm.hasModelInCache(await resolveLlmModel(model))
  } catch (e) {
    return false
  }
}

/** onProgress({ stage: 'download', value: 0..1, text }) while the model loads. */
export async function downloadWritingModel(model, onProgress) {
  await getLlm(model, onProgress)
}

async function getLlm(model, onProgress = () => {}) {
  const id = await resolveLlmModel(model)
  if (llm && llmModel === id) return llm
  const webllm = await import('@mlc-ai/web-llm')
  const worker = new Worker(new URL('./llm.worker.js', import.meta.url), { type: 'module' })
  try {
    llm = await webllm.CreateWebWorkerMLCEngine(worker, id, {
      initProgressCallback: (report) => onProgress({ stage: 'download', value: report.progress || 0, text: report.text }),
    })
  } catch (e) {
    worker.terminate()
    throw friendlyError(e?.message || String(e), 'writing')
  }
  llmModel = id
  return llm
}

/** With `schema`, the model is held to that JSON shape while it writes. */
async function complete(config, prompt, { schema = null, onProgress } = {}) {
  const engine = await getLlm(config.llm_model, onProgress)
  onProgress?.({ stage: 'write', value: 0 })
  const request = {
    messages: [
      { role: 'system', content: config.system_prompt },
      { role: 'user', content: prompt },
    ],
    temperature: 0.2,
    max_tokens: 1200,
  }
  let reply
  try {
    // WebLLM's json_object mode needs an explicit schema string: without one its grammar
    // compiler fails with "Cannot pass non-string to std::string".
    reply = await engine.chat.completions.create(
      schema ? { ...request, response_format: { type: 'json_object', schema: JSON.stringify(schema) } } : request,
    )
  } catch (e) {
    // If constrained writing isn't available on this device, ask plainly; parseJson
    // copes with JSON wrapped in prose or code fences.
    if (!schema || !/grammar/i.test(`${e?.name} ${e?.message}`)) throw e
    reply = await engine.chat.completions.create(request)
  }
  return (reply.choices?.[0]?.message?.content || '').trim()
}

/** Summary, highlights and suggested questions, as { summary, highlights, questions }. */
export async function writeInsights(config, segments, onProgress = () => {}) {
  const parts = splitTranscript(segments, PART_CHARS)
  let reply
  if (parts.length <= 1) {
    reply = await complete(config, fill(config.prompts.insights, { transcript: lines(segments).join('\n') }), {
      schema: config.insights_schema,
      onProgress,
    })
  } else {
    const notes = await partNotes(config, parts, onProgress)
    reply = await complete(config, fill(config.prompts.insights_from_parts, { transcript: notes.join('\n\n') }), {
      schema: config.insights_schema,
      onProgress,
    })
  }
  const data = parseJson(reply)
  if (!data || !data.summary) throw new Error('The model did not answer in the expected format. Try again.')
  return data
}

export async function writeSop(config, segments, onProgress = () => {}) {
  const parts = splitTranscript(segments, PART_CHARS)
  const transcript = parts.length <= 1 ? lines(segments).join('\n') : (await partNotes(config, parts, onProgress)).join('\n\n')
  const sop = await complete(config, fill(config.prompts.sop, { transcript }), { onProgress })
  if (!sop) throw new Error('The model returned nothing. Try again.')
  return sop
}

export async function answer(config, segments, question, onProgress = () => {}) {
  const transcript = relevantLines(segments, question, ASK_CHARS).join('\n')
  return complete(config, fill(config.prompts.ask, { transcript, question }), { onProgress })
}

async function partNotes(config, parts, onProgress) {
  const notes = []
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]
    notes.push(
      await complete(
        config,
        fill(config.prompts.part, {
          start: formatTime(part[0].start),
          end: formatTime(part[part.length - 1].end),
          transcript: lines(part).join('\n'),
        }),
        { onProgress: (p) => onProgress(p.stage === 'write' ? { stage: 'write', value: i / parts.length } : p) },
      ),
    )
  }
  return notes
}

/** Download and device problems explained in plain words. */
function friendlyError(message, model) {
  const text = String(message || '')
  if (/fetch|network|load failed|ERR_|CORS/i.test(text)) {
    return new Error(
      `Could not download the ${model} model. Check your internet connection and try again.`,
      { cause: message },
    )
  }
  if (/memory|OOM|allocation/i.test(text)) {
    return new Error(`This device ran out of memory running the ${model} model. Close other tabs, or ask your admin for a smaller model.`)
  }
  return new Error(text || `The ${model} model stopped unexpectedly.`)
}

// ---------------------------------------------------------------- text helpers (mirror ai.py)

/** Fills a Python-style template: {name} is replaced, {{ and }} become literal braces. */
export function fill(template, values) {
  return template.replace(/\{\{|\}\}|\{(\w+)\}/g, (match, name) => {
    if (match === '{{') return '{'
    if (match === '}}') return '}'
    return values[name] ?? ''
  })
}

export function formatTime(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

export function lines(segments) {
  return segments.map((s) => `[${formatTime(s.start)}] ${s.text}`)
}

export function splitTranscript(segments, maxChars) {
  const parts = []
  let current = []
  let size = 0
  for (const segment of segments) {
    const length = segment.text.length + 10
    if (current.length && size + length > maxChars) {
      parts.push(current)
      current = []
      size = 0
    }
    current.push(segment)
    size += length
  }
  if (current.length) parts.push(current)
  return parts
}

export function relevantLines(segments, question, maxChars) {
  const all = lines(segments)
  if (all.reduce((sum, l) => sum + l.length + 1, 0) <= maxChars) return all

  const words = new Set((question.toLowerCase().match(/\w{3,}/g) || []))
  const scores = segments.map((s) => (s.text.toLowerCase().match(/\w{3,}/g) || []).filter((w) => words.has(w)).length)
  const ranked = [...scores.keys()].sort((a, b) => scores[b] - scores[a])

  const chosen = new Set()
  let size = 0
  for (const index of ranked) {
    for (const i of [index - 1, index, index + 1]) {
      if (i >= 0 && i < all.length && !chosen.has(i) && size + all[i].length + 1 <= maxChars) {
        chosen.add(i)
        size += all[i].length + 1
      }
    }
    if (size >= maxChars * 0.9) break
  }
  return [...chosen].sort((a, b) => a - b).map((i) => all[i])
}

/** Small models sometimes wrap JSON in prose or code fences. */
export function parseJson(text) {
  try {
    return JSON.parse(text)
  } catch (e) {
    const match = text.match(/\{[\s\S]*\}/)
    if (!match) return null
    try {
      return JSON.parse(match[0])
    } catch (err) {
      return null
    }
  }
}
