/**
 * Diligenx mark: a folded document whose fold doubles as a check, set on a
 * gradient tile. `tone="dark"` is for dark surfaces (marketing hero, login
 * panel), where the wordmark turns white.
 */
export function LogoMark({ className = 'w-7 h-7' }: { className?: string }) {
  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center rounded-[28%] bg-gradient-to-br from-blue-500 via-blue-600 to-violet-600 shadow-[0_2px_8px_-2px_rgb(74_85_232/0.6),inset_0_1px_0_0_rgb(255_255_255/0.25)] ${className}`}
      aria-hidden
    >
      <svg viewBox="0 0 24 24" className="w-[58%] h-[58%] text-white" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 3H7.5A2.5 2.5 0 005 5.5v13A2.5 2.5 0 007.5 21h9a2.5 2.5 0 002.5-2.5V8z" />
        <path d="M14 3v5h5" opacity={0.55} />
        <path d="M9 14.5l2 2 4-4.5" />
      </svg>
    </span>
  )
}

export default function Logo({
  tone = 'light',
  size = 'md',
}: {
  tone?: 'light' | 'dark'
  size?: 'sm' | 'md'
}) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark className={size === 'sm' ? 'w-6 h-6' : 'w-7 h-7'} />
      <span
        className={`font-semibold tracking-tight ${size === 'sm' ? 'text-sm' : 'text-[15px]'} ${
          tone === 'dark' ? 'text-white' : 'text-slate-900'
        }`}
      >
        Diligenx
      </span>
    </span>
  )
}
