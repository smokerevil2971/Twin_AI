import { useRef, useState } from 'react'
import { Upload, File, X } from 'lucide-react'

export default function FileUploadZone({ accept, maxMB = 20, onFile, label }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const [file, setFile]         = useState(null)
  const [error, setError]       = useState('')

  function handleFile(f) {
    if (!f) return
    if (maxMB && f.size > maxMB * 1024 * 1024) {
      setError(`File size must be under ${maxMB}MB`)
      return
    }
    setError('')
    setFile(f)
    onFile?.(f)
  }

  return (
    <div>
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]) }}
        onClick={() => inputRef.current?.click()}
        className="border-2 border-dashed rounded-card p-8 flex flex-col items-center gap-3 cursor-pointer transition-all"
        style={{
          borderColor: dragging ? '#6C63FF' : 'var(--border)',
          background:  dragging ? 'rgba(108,99,255,0.05)' : 'transparent',
        }}
      >
        <Upload size={28} className="text-text-secondary" />
        <div className="text-center">
          <p className="text-sm font-medium text-text-primary">
            {label || 'Drag & drop or click to upload'}
          </p>
          <p className="text-xs text-text-muted mt-1">
            {accept || 'PDF, PNG, JPG, WEBP, TXT, MD'} · max {maxMB}MB
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          onChange={e => handleFile(e.target.files[0])}
        />
      </div>

      {error && <p className="text-danger text-xs mt-1">{error}</p>}

      {file && (
        <div className="flex items-center gap-2 mt-3 px-3 py-2 rounded-lg bg-bg-raised border border-border">
          <File size={14} className="text-text-secondary shrink-0" />
          <span className="text-sm text-text-primary truncate flex-1">{file.name}</span>
          <span className="text-xs text-text-muted">{(file.size / 1024).toFixed(0)} KB</span>
          <button onClick={e => { e.stopPropagation(); setFile(null); onFile?.(null) }}>
            <X size={14} className="text-text-secondary hover:text-danger" />
          </button>
        </div>
      )}
    </div>
  )
}
