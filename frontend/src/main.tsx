import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Sentinel Telemetry Operator fonts. Loaded as packages (not a CDN link)
// so the console renders identically offline and in CI screenshots.
import '@fontsource/space-grotesk/500.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource-variable/geist'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/600.css'

import { App } from '@/App'
import '@/styles/index.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('Root element #root is missing from index.html')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
