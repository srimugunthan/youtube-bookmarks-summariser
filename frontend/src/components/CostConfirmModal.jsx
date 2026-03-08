import { useState } from 'react'

function Row({ label, model, inputTokens, outputTokens, cost }) {
  return (
    <tr className="border-t border-gray-100">
      <td className="py-2 pr-4 text-sm text-gray-700 font-medium">{label}</td>
      <td className="py-2 pr-4 text-xs text-gray-400 font-mono">{model}</td>
      <td className="py-2 pr-4 text-sm text-gray-600 text-right">{(inputTokens ?? 0).toLocaleString()}</td>
      <td className="py-2 pr-4 text-sm text-gray-600 text-right">{(outputTokens ?? 0).toLocaleString()}</td>
      <td className="py-2 text-sm text-gray-800 font-semibold text-right">${(cost ?? 0).toFixed(4)}</td>
    </tr>
  )
}

export default function CostConfirmModal({ jobId, estimate, onDone }) {
  const [loading, setLoading] = useState(null)  // 'confirming' | 'cancelling' | null

  const handleConfirm = async () => {
    setLoading('confirming')
    try {
      await fetch(`/api/jobs/${jobId}/confirm`, { method: 'POST' })
    } finally {
      onDone(true)
    }
  }

  const handleCancel = async () => {
    setLoading('cancelling')
    try {
      await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' })
    } finally {
      onDone(false)
    }
  }

  const summarizer = estimate?.by_agent?.summarizer ?? {}
  const synthesis = estimate?.by_agent?.synthesis ?? {}

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="px-6 py-5 border-b border-gray-100">
          <h2 className="text-lg font-bold text-gray-800">Confirm processing cost</h2>
          <p className="text-sm text-gray-500 mt-1">
            {estimate?.available_count ?? 0} videos available
            {(estimate?.unavailable_count ?? 0) > 0 && (
              <span className="text-gray-400">
                {' '}· {estimate.unavailable_count} unavailable (will be skipped)
              </span>
            )}
          </p>
        </div>

        {/* Cost table */}
        <div className="px-6 py-4 overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="pb-2 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">Agent</th>
                <th className="pb-2 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">Model</th>
                <th className="pb-2 text-right text-xs font-semibold text-gray-400 uppercase tracking-wide">Input</th>
                <th className="pb-2 text-right text-xs font-semibold text-gray-400 uppercase tracking-wide">Output</th>
                <th className="pb-2 text-right text-xs font-semibold text-gray-400 uppercase tracking-wide">Cost</th>
              </tr>
            </thead>
            <tbody>
              <Row
                label="Summarizer"
                model={estimate?.flash_model ?? ''}
                inputTokens={(estimate?.summarizer_input_tokens ?? 0) + (estimate?.chunk_summarizer_input_tokens ?? 0)}
                outputTokens={(estimate?.summarizer_output_tokens ?? 0) + (estimate?.chunk_summarizer_output_tokens ?? 0)}
                cost={summarizer.cost_usd}
              />
              <Row
                label="Synthesis"
                model={estimate?.pro_model ?? ''}
                inputTokens={estimate?.synthesis_input_tokens}
                outputTokens={estimate?.synthesis_output_tokens}
                cost={synthesis.cost_usd}
              />
              <tr className="border-t-2 border-gray-200">
                <td colSpan={4} className="pt-3 pb-1 text-sm font-bold text-gray-700">Total</td>
                <td className="pt-3 pb-1 text-right text-base font-bold text-indigo-600">
                  ${(estimate?.total_cost_usd ?? 0).toFixed(4)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Token totals */}
        <div className="flex gap-4 px-6 pb-4 text-xs text-gray-400">
          <span>{(estimate?.total_input_tokens ?? 0).toLocaleString()} input tokens</span>
          <span>·</span>
          <span>{(estimate?.total_output_tokens ?? 0).toLocaleString()} output tokens</span>
        </div>

        {/* Actions */}
        <div className="flex gap-3 px-6 py-4 border-t border-gray-100 bg-slate-50">
          <button
            onClick={handleCancel}
            disabled={loading !== null}
            className="flex-1 py-2.5 rounded-xl text-sm font-medium text-gray-600 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-40 transition"
          >
            {loading === 'cancelling' ? 'Cancelling…' : 'Cancel'}
          </button>
          <button
            onClick={handleConfirm}
            disabled={loading !== null}
            className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white bg-indigo-500 hover:bg-indigo-600 disabled:opacity-40 transition shadow-sm"
          >
            {loading === 'confirming' ? (
              <span className="flex items-center justify-center gap-2">
                <span className="inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Confirming…
              </span>
            ) : (
              `Proceed · $${(estimate?.total_cost_usd ?? 0).toFixed(4)}`
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
