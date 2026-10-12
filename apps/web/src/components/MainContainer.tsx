'use client'

import { usePathname } from 'next/navigation'

// Pages that draw their own full-bleed chrome (marketing landing, sign-in).
const FULL_BLEED = new Set(['/', '/login'])

/** The root `<main>`: constrained for app pages, edge-to-edge for marketing. */
export default function MainContainer({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  if (FULL_BLEED.has(pathname)) {
    return <main className="w-full flex-1">{children}</main>
  }
  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8 sm:py-10 w-full flex-1 animate-fade-in">
      {children}
    </main>
  )
}
