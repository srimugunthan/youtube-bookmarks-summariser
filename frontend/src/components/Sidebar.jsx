import { useEffect, useState } from 'react'

function KeyIcon() {
  return (
    <svg
      className="w-5 h-5 text-gray-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z"
      />
    </svg>
  )
}

function EyeIcon({ open }) {
  if (open) {
    return (
      <svg className="w-4 h-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    )
  }
  return (
    <svg className="w-4 h-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
    </svg>
  )
}

export default function Sidebar({ apiKey, onApiKeyChange }) {
  const [showKey, setShowKey] = useState(false)
  const [hasServerKey, setHasServerKey] = useState(false)

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data) => setHasServerKey(!!data.has_server_key))
      .catch(() => {})
  }, [])

  // Server key is active when .env has a key and no local override is entered
  const serverKeyActive = hasServerKey && !apiKey

  return (
    <aside className="w-72 min-w-[18rem] bg-white border-r border-gray-100 flex flex-col p-6 gap-5 shadow-sm">
      {/* Icon */}
      <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-slate-50 border border-gray-100">
        <KeyIcon />
      </div>

      {/* API key section */}
      <div className="flex flex-col gap-2">
        <label className="text-sm font-semibold text-gray-700">
          Google API Key
        </label>

        {serverKeyActive ? (
          <div className="flex items-center px-3 py-2 bg-slate-50 border border-gray-200 rounded-lg">
            <span className="flex-1 text-sm tracking-widest text-gray-400 select-none">
              ••••••••••••••••
            </span>
            <span className="text-xs text-emerald-600 font-medium ml-2 whitespace-nowrap">from .env</span>
          </div>
        ) : (
          <div className="relative">
            <input
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => onApiKeyChange(e.target.value)}
              placeholder="Enter your API key"
              spellCheck={false}
              className="w-full px-3 py-2 pr-9 text-sm border border-gray-200 rounded-lg bg-slate-50 text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition"
            />
            <button
              type="button"
              onClick={() => setShowKey((v) => !v)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition"
              aria-label={showKey ? 'Hide key' : 'Show key'}
            >
              <EyeIcon open={showKey} />
            </button>
          </div>
        )}

        <p className="text-xs text-gray-400 leading-relaxed">
          {serverKeyActive
            ? 'A key is configured on the server. Enter one here to override it.'
            : 'Your API key is stored locally and never sent to our servers.'}
        </p>
      </div>

      {/* Key status indicator */}
      {(apiKey || serverKeyActive) && (
        <div className="flex items-center gap-1.5 text-xs text-emerald-600 font-medium">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />
          {serverKeyActive ? 'Server key active' : 'API key saved'}
        </div>
      )}

      {/* Divider + info */}
      <div className="mt-auto border-t border-gray-100 pt-4">
        <p className="text-xs text-gray-400">
          Get a free key at{' '}
          <span className="font-medium text-gray-500">
            aistudio.google.com
          </span>
        </p>
      </div>
    </aside>
  )
}
