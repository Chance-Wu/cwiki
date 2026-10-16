import '@fontsource/noto-serif-sc/600.css'
import { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'
import { unstable_HistoryRouter as HistoryRouter } from 'react-router-dom'
import { ThemeProvider } from './theme/ThemeProvider'
import { history } from './lib/history'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <HistoryRouter
      history={history}
      future={{ v7_startTransition: false, v7_relativeSplatPath: true }}
    >
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </HistoryRouter>
  </StrictMode>,
)
