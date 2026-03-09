import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle, ArrowRight } from 'lucide-react'
import toast from 'react-hot-toast'
import FileUploadZone from '../components/ui/FileUploadZone'
import clsx from 'clsx'
import { useAuth } from '../context/AuthContext'

const STEPS = [
  { title: 'Business Profile', desc: 'Name, logo, language' },
  { title: 'Upload Clients', desc: 'Import CSV/Excel' },
  { title: 'Opt-in Confirmation', desc: 'Mandatory consent', required: true },
  { title: 'Upload Document', desc: 'Add first product/offer' },
  { title: 'Test Broadcast', desc: 'Send to yourself' },
  { title: 'Test Bot', desc: 'Chat with the bot' },
  { title: 'Flagged Messages', desc: 'Review inbox' },
  { title: 'Go Live', desc: 'Send first real broadcast', required: true },
]

export default function Onboarding() {
  const [step, setStep] = useState(0)
  const nav = useNavigate()
  const { user } = useAuth()

  // Step 3 state
  const [optin, setOptin] = useState(false)

  function next() {
    if (step === 2 && !optin) {
      toast.error('You must confirm opt-in consent to proceed.')
      return
    }
    if (step === STEPS.length - 1) {
      toast.success('Onboarding complete! Welcome to Twin AI.')
      nav('/dashboard')
      return
    }
    setStep(s => s + 1)
  }

  function skip() {
    if (STEPS[step].required) {
      toast.error('This step is mandatory and cannot be skipped.')
      return
    }
    setStep(s => s + 1)
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6" style={{ background: 'var(--bg-app)' }}>
      <div className="w-full max-w-2xl">
        
        {/* Stepper Header */}
        <div className="flex items-center justify-between mb-8">
          {STEPS.map((s, i) => (
            <div key={i} className="flex flex-col items-center gap-2 flex-1 relative">
              <div
                className={clsx(
                  'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-colors z-10',
                  i === step ? 'bg-accent text-white ring-4 ring-accent/20' :
                  i < step   ? 'bg-success text-white' : 'bg-bg-card text-text-muted border border-border'
                )}
              >
                {i < step ? <CheckCircle size={16} /> : i + 1}
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className="absolute top-4 left-1/2 w-full h-[2px] -z-0"
                  style={{ background: i < step ? 'var(--success)' : 'var(--border)' }}
                />
              )}
            </div>
          ))}
        </div>

        {/* Step Content */}
        <div className="card p-8 min-h-[400px] flex flex-col" style={{ animation: 'fadeIn 0.3s' }}>
          
          <div className="mb-8 text-center">
            <h1 className="text-2xl font-bold text-text-primary mb-2">{STEPS[step].title}</h1>
            <p className="text-text-secondary">{STEPS[step].desc}</p>
          </div>

          <div className="flex-1 flex flex-col justify-center max-w-md mx-auto w-full">
            {step === 0 && (
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-text-secondary mb-1.5">Business Name</label>
                  <input type="text" placeholder="Your Retail Store" className="w-full bg-bg-input border border-border rounded-lg px-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-accent" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-text-secondary mb-1.5">Language</label>
                  <select className="w-full bg-bg-input border border-border rounded-lg px-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-accent">
                    <option>English</option>
                    <option>Hindi</option>
                  </select>
                </div>
              </div>
            )}

            {step === 1 && (
              <FileUploadZone accept=".csv,.xlsx" label="Upload your client list" maxMB={10} />
            )}

            {step === 2 && (
              <div className="p-4 rounded-lg bg-warning/10 border border-warning/30 flex items-start gap-3">
                <input type="checkbox" checked={optin} onChange={e => setOptin(e.target.checked)} className="mt-1 accent-accent w-4 h-4" />
                <p className="text-sm text-warning leading-relaxed">
                  I confirm that all imported clients have explicitly opted-in to receive WhatsApp messages from my business. I understand that sending unsolicited messages may result in a ban from the WhatsApp API.
                </p>
              </div>
            )}

            {step === 3 && (
              <FileUploadZone accept=".pdf,.png" label="Upload your first product catalog or offer flyer" />
            )}

            {step === 4 && (
              <div className="space-y-4 text-center">
                <p className="text-sm text-text-secondary">Send a test broadcast to yourself to see how it looks.</p>
                <button className="btn-primary mx-auto" onClick={() => toast.success('Test broadcast sent via Celery!')}>Send to {user?.email}</button>
              </div>
            )}

            {step === 5 && (
              <div className="text-center">
                <p className="text-sm text-text-secondary">Message your business WhatsApp number and ask a question about the document you just uploaded. The bot should answer automatically.</p>
              </div>
            )}

            {step === 6 && (
              <div className="text-center">
                <p className="text-sm text-text-secondary">If the bot is unsure, it flags the message. Go to your Conversations screen to review and manually answer flagged messages.</p>
              </div>
            )}

            {step === 7 && (
              <div className="text-center">
                <p className="text-sm text-text-secondary">You're ready! Send your first real broadcast to a small segment (10-20 clients) to start warming up your number.</p>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between mt-8 pt-6 border-t border-border">
            {!STEPS[step].required ? (
              <button className="text-sm text-text-muted hover:text-text-primary transition-colors" onClick={skip}>
                Skip for now
              </button>
            ) : <div />}
            
            <button className="btn-primary" onClick={next}>
              {step === STEPS.length - 1 ? 'Finish' : 'Continue'} <ArrowRight size={16} />
            </button>
          </div>

        </div>
      </div>
    </div>
  )
}
