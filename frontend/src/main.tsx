import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { EvaluatePage } from './pages/EvaluatePage.tsx'
import { EvaluateLivePage } from './pages/EvaluateLivePage.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/evaluate" element={<EvaluatePage />} />
        <Route path="/evaluate/live" element={<EvaluateLivePage />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
