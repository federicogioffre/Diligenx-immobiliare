import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono, Instrument_Serif } from 'next/font/google'
import './globals.css'
import NavBar from '@/components/NavBar'
import AppFooter from '@/components/AppFooter'
import CookieBanner from '@/components/CookieBanner'
import MainContainer from '@/components/MainContainer'
import ThemeProvider, { THEME_BOOT_SCRIPT } from '@/components/theme/ThemeProvider'
import ThemedToaster from '@/components/theme/ThemedToaster'

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
  'Diligenx Immobiliare — due diligence assistita da AI per l’acquisto di un immobile: provenienza, ipoteche, catasto, urbanistica, condominio e relazione per il rogito.'

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
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body className="app-backdrop min-h-screen flex flex-col" suppressHydrationWarning>
        <ThemeProvider>
          <NavBar />
          <MainContainer>{children}</MainContainer>
          <AppFooter />
          <CookieBanner />
          {/* Global toast outlet. Errors are rendered as inline banners (see
              components/ui/ErrorAlert); toasts are reserved for success
              feedback on short-lived actions (create, rename, delete, etc.). */}
          <ThemedToaster />
        </ThemeProvider>
      </body>
    </html>
  )
}
