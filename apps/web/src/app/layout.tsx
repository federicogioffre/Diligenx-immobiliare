import type { Metadata } from 'next'
import { Toaster } from 'sonner'
import './globals.css'
import NavBar from '@/components/NavBar'
import AppFooter from '@/components/AppFooter'
import CookieBanner from '@/components/CookieBanner'

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

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="it" suppressHydrationWarning>
      <body className="bg-slate-50 min-h-screen flex flex-col" suppressHydrationWarning>
        <NavBar />
        <main className="max-w-6xl mx-auto px-6 py-8 w-full flex-1">{children}</main>
        <AppFooter />
        <CookieBanner />
        {/* Global toast outlet. Errors are rendered as inline banners (see
            components/ui/ErrorAlert); toasts are reserved for success
            feedback on short-lived actions (create, rename, delete, etc.). */}
        <Toaster
          position="top-right"
          richColors
          closeButton
          toastOptions={{ duration: 3500 }}
        />
      </body>
    </html>
  )
}
