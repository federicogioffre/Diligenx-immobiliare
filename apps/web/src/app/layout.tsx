import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono, Instrument_Serif } from 'next/font/google'
import { Toaster } from 'sonner'
import './globals.css'
import NavBar from '@/components/NavBar'
import AppFooter from '@/components/AppFooter'
import CookieBanner from '@/components/CookieBanner'
import MainContainer from '@/components/MainContainer'

// Self-hosted at build time by next/font: no request to Google from the
// visitor's browser (the CDN @import used to send every IP to Google Fonts).
const sans = Geist({ subsets: ['latin'], variable: '--font-sans', display: 'swap' })
const mono = Geist_Mono({ subsets: ['latin'], variable: '--font-mono', display: 'swap' })
const display = Instrument_Serif({
  subsets: ['latin'],
  weight: '400',
  style: ['normal', 'italic'],
  variable: '--font-display',
  display: 'swap',
})

const SITE_URL = 'https://diligenx.it'
const SITE_DESCRIPTION =
  'Diligenx — piattaforma di due diligence legale assistita da AI: analisi di contratti e documenti societari, red flag e report professionali.'

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  applicationName: 'Diligenx',
  title: {
    default: 'Diligenx — Legal Due Diligence Platform',
    template: '%s — Diligenx',
  },
  description: SITE_DESCRIPTION,
  robots: { index: true, follow: true },
  openGraph: {
    type: 'website',
    siteName: 'Diligenx',
    title: 'Diligenx — Legal Due Diligence Platform',
    description: SITE_DESCRIPTION,
    url: SITE_URL,
    locale: 'it_IT',
  },
  twitter: {
    card: 'summary',
    title: 'Diligenx — Legal Due Diligence Platform',
    description: SITE_DESCRIPTION,
  },
}

export const viewport: Viewport = {
  themeColor: '#0a0b14',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="it" className={`${sans.variable} ${mono.variable} ${display.variable}`} suppressHydrationWarning>
      <body className="app-backdrop min-h-screen flex flex-col" suppressHydrationWarning>
        <NavBar />
        <MainContainer>{children}</MainContainer>
        <AppFooter />
        <CookieBanner />
        {/* Global toast outlet. Errors are rendered as inline banners (see
            components/ui/ErrorAlert); toasts are reserved for success
            feedback on short-lived actions (create, rename, delete, etc.). */}
        <Toaster
          position="top-right"
          richColors
          closeButton
          toastOptions={{ duration: 3500, className: 'font-sans' }}
        />
      </body>
    </html>
  )
}
