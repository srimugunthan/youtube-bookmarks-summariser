import { useState } from 'react'

function RefreshIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
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
  const report = result?.token_report ?? {}
  const jobId = result?.job_id

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
        <span className="flex-1 text-sm font-semibold text-gray-700 text-center">
          Job complete
        </span>
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

      {/* Download cards */}
      <div className="flex-1 flex flex-col items-center justify-center gap-5 px-8">
        <p className="text-sm text-gray-500 mb-2">Your files are ready to download.</p>

        <a
          href={`/api/jobs/${jobId}/download`}
          download
          className="flex items-center gap-4 w-full max-w-sm px-5 py-4 bg-white border border-gray-200 rounded-2xl shadow-sm hover:shadow-md hover:border-indigo-200 transition group"
        >
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-indigo-50 text-indigo-500 group-hover:bg-indigo-100 transition flex-shrink-0">
            <DownloadIcon />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-800">overall_summary.md</p>
            <p className="text-xs text-gray-400 mt-0.5">Synthesized summary of all videos</p>
          </div>
        </a>

        <a
          href={`/api/jobs/${jobId}/transcripts`}
          download
          className="flex items-center gap-4 w-full max-w-sm px-5 py-4 bg-white border border-gray-200 rounded-2xl shadow-sm hover:shadow-md hover:border-indigo-200 transition group"
        >
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-slate-100 text-slate-500 group-hover:bg-slate-200 transition flex-shrink-0">
            <DownloadIcon />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-800">transcripts.md</p>
            <p className="text-xs text-gray-400 mt-0.5">Individual per-video summaries</p>
          </div>
        </a>
      </div>
    </div>
  )
}
