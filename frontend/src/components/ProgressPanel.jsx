import { useEffect, useRef, useState } from 'react'
import CostConfirmModal from './CostConfirmModal'

function CheckIcon() {
  return (
    <svg className="w-4 h-4 text-emerald-500 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  )
}

function XIcon() {
  return (
    <svg className="w-4 h-4 text-red-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

function SpinnerIcon({ className = 'w-4 h-4' }) {
  return (
    <span className={`inline-block border-2 border-indigo-300 border-t-indigo-600 rounded-full animate-spin flex-shrink-0 ${className}`} />
  )
}

function VideoRow({ index, total, title, status, transcriptType, tokens, error }) {
  const padded = String(index).padStart(String(total).length, ' ')

  return (
    <div className="flex items-start gap-3 py-2 px-4 hover:bg-gray-50 rounded-lg transition">
      <span className="text-xs text-gray-400 font-mono mt-0.5 flex-shrink-0">
        [{padded}/{total}]
      </span>

      {status === 'done'        && <CheckIcon />}
      {status === 'failed'      && <XIcon />}
      {status === 'summarizing' && <SpinnerIcon />}
      {status === 'pending'     && <span className="w-4 h-4 flex-shrink-0" />}

      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-700 truncate font-medium">{title || `Video ${index}`}</p>
        {transcriptType && status === 'done' && (
          <p className="text-xs text-gray-400 mt-0.5">
            {transcriptType}
            {tokens ? ` · ${tokens.toLocaleString()} tokens` : ''}
          </p>
        )}
        {error && <p className="text-xs text-red-400 mt-0.5">{error}</p>}
      </div>
    </div>
  )
}

// phase: 'fetching' | 'confirming' | 'summarizing' | 'synthesizing' | 'done' | 'failed' | 'cancelled'
export default function ProgressPanel({ jobId, onJobComplete }) {
  const [phase, setPhase] = useState('fetching')
  const [totalVideos, setTotalVideos] = useState(0)
  const [videos, setVideos] = useState([])
  const [summaryCount, setSummaryCount] = useState(0)
  const [errorMsg, setErrorMsg] = useState(null)
  const [estimate, setEstimate] = useState(null)
  const logRef = useRef(null)

  // Auto-scroll log area
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [videos, phase])

  useEffect(() => {
    const es = new EventSource(`/api/jobs/${jobId}/stream`)

    const onEvent = (type, handler) => es.addEventListener(type, (e) => handler(JSON.parse(e.data)))

    onEvent('confirmation_required', (data) => {
      setEstimate(data.estimate)
      setPhase('confirming')
    })

    onEvent('job_started', (data) => {
      setPhase('summarizing')
      setTotalVideos(data.total_videos)
      setVideos(Array.from({ length: data.total_videos }, (_, i) => ({
        index: i + 1,
        title: null,
        status: 'pending',
        transcriptType: null,
        tokens: null,
        error: null,
      })))
    })

    onEvent('video_started', (data) => {
      setVideos((prev) => prev.map((v) =>
        v.index === data.index
          ? { ...v, title: data.title, status: 'summarizing' }
          : v
      ))
    })

    onEvent('video_done', (data) => {
      setVideos((prev) => prev.map((v) =>
        v.status === 'summarizing' && (!data.title || v.title === data.title)
          ? { ...v, status: 'done', transcriptType: data.transcript_type, tokens: data.tokens_used }
          : v
      ))
    })

    onEvent('video_failed', (data) => {
      setVideos((prev) => prev.map((v) =>
        v.status === 'summarizing' && (!data.title || v.title === data.title)
          ? { ...v, status: 'failed', error: data.error }
          : v
      ))
    })

    onEvent('synthesis_start', (data) => {
      setPhase('synthesizing')
      setSummaryCount(data.summary_count)
    })

    onEvent('job_done', async () => {
      setPhase('done')
      es.close()
      try {
        const resp = await fetch(`/api/jobs/${jobId}/result`)
        const result = await resp.json()
        onJobComplete(result)
      } catch {
        setErrorMsg('Job finished but failed to load result.')
      }
    })

    onEvent('job_cancelled', () => {
      setPhase('cancelled')
      es.close()
    })

    onEvent('job_failed', (data) => {
      setPhase('failed')
      setErrorMsg(data.error || 'An unknown error occurred.')
      es.close()
    })

    es.onerror = () => {
      // Only treat as failure if we haven't already reached a terminal state
      setPhase((prev) => {
        if (prev === 'done' || prev === 'cancelled' || prev === 'failed') return prev
        setErrorMsg('Lost connection to the server.')
        return 'failed'
      })
      es.close()
    }

    return () => es.close()
  }, [jobId, onJobComplete])

  const handleModalDone = (confirmed) => {
    // Close modal; phase will update via SSE (job_started or job_cancelled)
    if (!confirmed) {
      setPhase('cancelled')
    } else {
      setPhase('summarizing')
    }
    setEstimate(null)
  }

  const doneCount = videos.filter((v) => v.status === 'done').length
  const failedCount = videos.filter((v) => v.status === 'failed').length
  const progress = totalVideos > 0 ? (doneCount + failedCount) / totalVideos : 0

  const headerText = {
    fetching:     'Fetching transcripts…',
    confirming:   'Waiting for confirmation…',
    summarizing:  'Processing videos…',
    synthesizing: 'Synthesizing…',
    done:         'Done — loading result…',
    failed:       'Job failed',
    cancelled:    'Job cancelled',
  }[phase] ?? 'Processing…'

  return (
    <div className="flex flex-col h-full max-w-2xl mx-auto px-6 py-10 gap-6">
      {/* Cost confirm modal — rendered on top */}
      {phase === 'confirming' && estimate && (
        <CostConfirmModal jobId={jobId} estimate={estimate} onDone={handleModalDone} />
      )}

      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-800">{headerText}</h2>
        <p className="text-sm text-gray-500 mt-1">
          Job ID: <span className="font-mono text-gray-600">{jobId}</span>
        </p>
      </div>

      {/* Fetching spinner */}
      {phase === 'fetching' && (
        <div className="flex items-center gap-3 px-4 py-3 bg-slate-50 rounded-xl border border-gray-100">
          <SpinnerIcon className="w-5 h-5" />
          <p className="text-sm text-gray-600">Fetching YouTube transcripts…</p>
        </div>
      )}

      {/* Progress bar */}
      {totalVideos > 0 && phase === 'summarizing' && (
        <div>
          <div className="flex justify-between text-xs text-gray-500 mb-1.5">
            <span>Summarizing videos</span>
            <span>{doneCount + failedCount} / {totalVideos}</span>
          </div>
          <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-400 rounded-full transition-all duration-300"
              style={{ width: `${progress * 100}%` }}
            />
          </div>
          {failedCount > 0 && (
            <p className="text-xs text-red-400 mt-1">{failedCount} video{failedCount > 1 ? 's' : ''} skipped (no transcript)</p>
          )}
        </div>
      )}

      {/* Synthesis phase indicator */}
      {phase === 'synthesizing' && (
        <div className="flex items-center gap-3 px-4 py-3 bg-indigo-50 rounded-xl border border-indigo-100">
          <SpinnerIcon className="w-5 h-5" />
          <div>
            <p className="text-sm font-medium text-indigo-700">
              Synthesizing {summaryCount} summaries
            </p>
            <p className="text-xs text-indigo-400 mt-0.5">Using Gemini Pro — this may take a moment</p>
          </div>
        </div>
      )}

      {/* Cancelled state */}
      {phase === 'cancelled' && (
        <div className="px-4 py-3 bg-amber-50 border border-amber-100 rounded-xl text-sm text-amber-700">
          Job cancelled. No API calls were made.
        </div>
      )}

      {/* Error state */}
      {phase === 'failed' && errorMsg && (
        <div className="px-4 py-3 bg-red-50 border border-red-100 rounded-xl text-sm text-red-600">
          {errorMsg}
        </div>
      )}

      {/* Video log */}
      {videos.length > 0 && (
        <div
          ref={logRef}
          className="flex-1 overflow-y-auto result-scroll border border-gray-100 rounded-2xl bg-white shadow-sm"
        >
          <div className="py-2">
            {videos.map((v) => (
              <VideoRow key={v.index} total={totalVideos} {...v} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state — waiting for first event */}
      {videos.length === 0 && phase !== 'failed' && phase !== 'cancelled' && phase !== 'fetching' && (
        <div className="flex-1 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3 text-gray-400">
            <SpinnerIcon className="w-8 h-8" />
            <p className="text-sm">Connecting to job stream…</p>
          </div>
        </div>
      )}
    </div>
  )
}
