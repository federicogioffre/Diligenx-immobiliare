'use client'

import { Toaster } from 'sonner'
import { useTheme } from './ThemeProvider'

export default function ThemedToaster() {
  const { resolved } = useTheme()
  return (
    <Toaster
      theme={resolved}
      position="top-right"
      richColors
      closeButton
      toastOptions={{ duration: 3500, className: 'font-sans' }}
    />
  )
}
