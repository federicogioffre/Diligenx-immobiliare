/**
 * Inline red error banner.
 *
 * Errors in DealMind are rendered as persistent banners (NOT toasts) because:
 *   1. They need to remain visible until the user addresses them.
 *   2. They often contain information the user must read (e.g. which file
 *      failed to upload, what validation rule broke).
 *
 * Success messages use sonner toasts instead — see app/layout.tsx.
 */
interface Props {
  error?: string | null
  className?: string
}

export default function ErrorAlert({ error, className = '' }: Props) {
  if (!error) return null
  return (
    <div
      role="alert"
      className={`flex items-start gap-2 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-4 py-3 ${className}`}
    >
      <svg
        className="w-4 h-4 shrink-0 mt-0.5"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        aria-hidden
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
      <span>{error}</span>
    </div>
  )
}
