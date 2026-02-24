import { useRef, useState } from 'react'

function RobotIcon() {
  return (
    <svg
      className="w-16 h-16 text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.2}
    >
      <rect x="3" y="8" width="18" height="12" rx="2" />
      <path strokeLinecap="round" d="M12 8V5" />
      <circle cx="12" cy="4" r="1" fill="currentColor" stroke="none" />
      <rect x="7" y="11" width="3" height="3" rx="0.5" fill="currentColor" stroke="none" />
      <rect x="14" y="11" width="3" height="3" rx="0.5" fill="currentColor" stroke="none" />
      <path strokeLinecap="round" d="M9 17h6" />
      <path d="M3 12H1M23 12h-2" strokeLinecap="round" />
    </svg>
  )
}

function FileIcon() {
  return (
    <svg className="w-5 h-5 text-gray-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  )
}

const STYLES = ['article', 'tutorial', 'guide']
const ACCEPT_TYPES = '.xml,.json,.txt'

export default function UploadForm({ apiKey, onJobStarted }) {
  const fileInputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [playlistUrl, setPlaylistUrl] = useState('')
  const [style, setStyle] = useState('article')
  const [title, setTitle] = useState('')
  const [maxVideos, setMaxVideos] = useState(50)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const canSubmit = (file || playlistUrl.trim()) && !loading

  const handleFileChange = (e) => {
    const chosen = e.target.files[0]
    if (chosen) {
      setFile(chosen)
      setPlaylistUrl('')   // clear the other input
    }
  }

  const handlePlaylistChange = (e) => {
    setPlaylistUrl(e.target.value)
    if (e.target.value) setFile(null)  // clear the other input
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const dropped = e.dataTransfer.files[0]
    if (dropped) {
      setFile(dropped)
      setPlaylistUrl('')
    }
  }

  const handleSubmit = async () => {
    if (!canSubmit) return
    setError(null)
    setLoading(true)

    const formData = new FormData()
    if (file) formData.append('file', file)
    if (playlistUrl.trim()) formData.append('playlist_url', playlistUrl.trim())
    formData.append('style', style)
    if (title.trim()) formData.append('title', title.trim())
    formData.append('max_videos', String(maxVideos))

    const headers = {}
    if (apiKey) headers['X-Gemini-Api-Key'] = apiKey

    try {
      const resp = await fetch('/api/jobs', {
        method: 'POST',
        headers,
        body: formData,
      })

      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `Server error ${resp.status}`)
      }
      onJobStarted(data.job_id)
    } catch (e) {
      setError(e.message)
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-full px-8 py-12">
      {/* Header */}
      <RobotIcon />
      <h1 className="mt-5 text-3xl font-bold text-center text-gray-800 leading-tight">
        Generate Youtube bookmarks/playlist
        <br />
        Transcript and summary
      </h1>
      <p className="mt-3 text-sm text-gray-500 text-center">
        Upload a youtube bookmarks file or enter a YouTube playlist URL
      </p>

      {/* Form card */}
      <div className="mt-10 w-full max-w-lg flex flex-col gap-4">

        {/* File drop zone */}
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-3 px-5 py-4 bg-gray-100 rounded-2xl cursor-pointer hover:bg-gray-200 transition select-none border-2 border-transparent hover:border-indigo-200"
        >
          <FileIcon />
          <span className="text-sm text-gray-600 truncate">
            {file ? file.name : 'Choose file   No file chosen'}
          </span>
          {file && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setFile(null); fileInputRef.current.value = '' }}
              className="ml-auto text-gray-400 hover:text-gray-600 text-xs"
            >
              ✕
            </button>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT_TYPES}
            className="hidden"
            onChange={handleFileChange}
          />
        </div>

        {/* OR divider */}
        <div className="flex items-center gap-3">
          <hr className="flex-1 border-gray-300" />
          <span className="text-xs font-medium text-gray-400 tracking-widest">OR</span>
          <hr className="flex-1 border-gray-300" />
        </div>

        {/* Playlist URL */}
        <input
          type="url"
          value={playlistUrl}
          onChange={handlePlaylistChange}
          placeholder="Enter YouTube playlist URL"
          className="w-full px-4 py-3.5 bg-gray-100 rounded-2xl text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-300 transition"
        />

        {/* Options row */}
        <div className="flex gap-3">
          {/* Style selector */}
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-500 mb-1 ml-1">Output style</label>
            <select
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              className="w-full px-3 py-2.5 bg-gray-100 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-300 transition cursor-pointer"
            >
              {STYLES.map((s) => (
                <option key={s} value={s}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {/* Max videos */}
          <div className="w-28">
            <label className="block text-xs font-medium text-gray-500 mb-1 ml-1">Max videos</label>
            <input
              type="number"
              min={1}
              max={200}
              value={maxVideos}
              onChange={(e) => setMaxVideos(Number(e.target.value))}
              className="w-full px-3 py-2.5 bg-gray-100 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-300 transition text-center"
            />
          </div>
        </div>

        {/* Optional title */}
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Custom output title (optional)"
          className="w-full px-4 py-3 bg-gray-100 rounded-2xl text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-300 transition"
        />

        {/* Error */}
        {error && (
          <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-xl px-4 py-2.5">
            {error}
          </p>
        )}

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="w-full mt-1 py-3.5 bg-indigo-400 text-white rounded-2xl text-sm font-semibold tracking-wide hover:bg-indigo-500 active:bg-indigo-600 disabled:opacity-40 disabled:cursor-not-allowed transition shadow-sm"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Submitting…
            </span>
          ) : (
            'GetTranscript and Summary'
          )}
        </button>
      </div>

      {/* Footer ad area placeholder */}
      <div className="mt-16 w-full max-w-lg h-16 border border-dashed border-gray-200 rounded-xl flex items-center justify-center">
        <span className="text-xs text-gray-300 tracking-widest uppercase">Advertisement Area</span>
      </div>
    </div>
  )
}
