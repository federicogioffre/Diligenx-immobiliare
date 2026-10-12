'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { selectInitialWorkspace, safeNextPath } from '@/lib/session'
import Spinner from '@/components/ui/Spinner'

// Landing page of a Microsoft or Google sign-in. The backend has already
// set the session cookie; this picks the workspace as the password login
// does, then continues to where the person was going.
export default function LoginCompletePage() {
  const router = useRouter()
  const [error, setError] = useState('')

  useEffect(() => {
    const next = safeNextPath(new URLSearchParams(window.location.search).get('next'))
    selectInitialWorkspace()
      .then(() => router.replace(next))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Accesso non riuscito'))
  }, [router])

  return (
    <div className="min-h-[60vh] flex items-center justify-center text-sm text-slate-500 gap-2">
      {error ? (
        <p className="text-red-600">
          {error} <a href="/login" className="underline">Torna al login</a>
        </p>
      ) : (
        <>
          <Spinner />
          Accesso in corso…
        </>
      )}
    </div>
  )
}
