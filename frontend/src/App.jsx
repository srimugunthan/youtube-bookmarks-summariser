import { useState } from 'react'
import Sidebar from './components/Sidebar'
import UploadForm from './components/UploadForm'
import ProgressPanel from './components/ProgressPanel'
import ResultView from './components/ResultView'

// view states: 'form' | 'progress' | 'result'
export default function App() {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('gemini_api_key') || '')
  const [view, setView] = useState('form')
  const [jobId, setJobId] = useState(null)
  const [result, setResult] = useState(null)

  const handleApiKeyChange = (key) => {
    setApiKey(key)
    localStorage.setItem('gemini_api_key', key)
  }

  const handleJobStarted = (id) => {
    setJobId(id)
    setView('progress')
  }

  const handleJobComplete = (jobResult) => {
    setResult(jobResult)
    setView('result')
  }

  const handleReset = () => {
    setJobId(null)
    setResult(null)
    setView('form')
  }

  return (
    <div className="flex h-screen bg-slate-50 font-sans">
      <Sidebar apiKey={apiKey} onApiKeyChange={handleApiKeyChange} />

      <main className="flex-1 overflow-auto">
        {view === 'form' && (
          <UploadForm
            apiKey={apiKey}
            onJobStarted={handleJobStarted}
          />
        )}
        {view === 'progress' && (
          <ProgressPanel
            jobId={jobId}
            onJobComplete={handleJobComplete}
          />
        )}
        {view === 'result' && (
          <ResultView
            result={result}
            onReset={handleReset}
          />
        )}
      </main>
    </div>
  )
}
