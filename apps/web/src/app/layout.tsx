import type { Metadata } from 'next'
import { Toaster } from 'sonner'
import './globals.css'
import NavBar from '@/components/NavBar'
import AppFooter from '@/components/AppFooter'
import CookieBanner from '@/components/CookieBanner'

export const metadata: Metadata = {
  title: 'Diligenx',
  description: 'AI-powered due diligence platform',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
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
