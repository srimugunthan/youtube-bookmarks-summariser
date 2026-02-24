import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useState } from 'react'

function DownloadIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  )
}

function RefreshIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
    </svg>
  )
}

function CopyIcon({ copied }) {
  if (copied) {
    return (
      <svg className="w-4 h-4 text-emerald-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
      </svg>
    )
  }
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
    </svg>
  )
}

function StatCard({ label, value, sub }) {
  return (
    <div className="flex flex-col gap-0.5 px-4 py-3 bg-slate-50 rounded-xl border border-gray-100">
      <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">{label}</span>
      <span className="text-lg font-bold text-gray-800">{value}</span>
      {sub && <span className="text-xs text-gray-400">{sub}</span>}
    </div>
  )
}

export default function ResultView({ result, onReset }) {
  const [copied, setCopied] = useState(false)
  const report = result?.token_report ?? {}

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(result?.content ?? '')
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard not available
    }
  }

  const handleDownload = () => {
    const blob = new Blob([result?.content ?? ''], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'result.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <header className="flex items-center gap-3 px-6 py-3.5 border-b border-gray-100 bg-white sticky top-0 z-10 shadow-sm">
        <button
          onClick={onReset}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition px-2 py-1 rounded-lg hover:bg-gray-100"
        >
          <RefreshIcon />
          New job
        </button>

        <span className="flex-1 text-sm font-semibold text-gray-700 text-center truncate px-4">
          {result?.content?.match(/^# (.+)/m)?.[1] ?? 'Synthesized Result'}
        </span>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            title="Copy markdown"
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition px-2.5 py-1.5 rounded-lg hover:bg-gray-100"
          >
            <CopyIcon copied={copied} />
            {copied ? 'Copied!' : 'Copy'}
          </button>
          <button
            onClick={handleDownload}
            title="Download result.md"
            className="flex items-center gap-1.5 text-sm text-white bg-indigo-400 hover:bg-indigo-500 transition px-3 py-1.5 rounded-lg font-medium"
          >
            <DownloadIcon />
            Download
          </button>
        </div>
      </header>

      {/* Stats bar */}
      {Object.keys(report).length > 0 && (
        <div className="flex gap-3 px-6 py-3 bg-slate-50 border-b border-gray-100 overflow-x-auto">
          <StatCard
            label="Total cost"
            value={`$${(report.total_cost_usd ?? 0).toFixed(4)}`}
          />
          <StatCard
            label="Input tokens"
            value={(report.total_input_tokens ?? 0).toLocaleString()}
          />
          <StatCard
            label="Output tokens"
            value={(report.total_output_tokens ?? 0).toLocaleString()}
          />
          {report.by_agent?.summarizer && (
            <StatCard
              label="Summarizer"
              value={`$${(report.by_agent.summarizer.cost_usd ?? 0).toFixed(4)}`}
              sub="Gemini Flash"
            />
          )}
          {report.by_agent?.synthesis && (
            <StatCard
              label="Synthesis"
              value={`$${(report.by_agent.synthesis.cost_usd ?? 0).toFixed(4)}`}
              sub="Gemini Pro"
            />
          )}
        </div>
      )}

      {/* Markdown content */}
      <div className="flex-1 overflow-y-auto result-scroll px-6 py-8">
        <article className="prose prose-slate max-w-3xl mx-auto">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {result?.content ?? ''}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  )
}
