interface Props {
  size?: 'sm' | 'md' | 'lg'
  tone?: 'blue' | 'white' | 'slate'
  className?: string
}

const SIZE: Record<NonNullable<Props['size']>, string> = {
  sm: 'w-3.5 h-3.5 border-2',
  md: 'w-4 h-4 border-2',
  lg: 'w-6 h-6 border-[3px]',
}

const TONE: Record<NonNullable<Props['tone']>, string> = {
  blue:  'border-blue-400 border-t-transparent',
  white: 'border-white border-t-transparent',
  slate: 'border-slate-400 border-t-transparent',
}

/**
 * Circular spinner matching the DealMind aesthetic.
 *
 *   <Spinner />                       // 16px blue
 *   <Spinner size="sm" tone="white"/> // 14px white (for use inside colored buttons)
 *   <Spinner size="lg" />             // 24px hero loader
 */
export default function Spinner({ size = 'md', tone = 'blue', className = '' }: Props) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={`${SIZE[size]} ${TONE[tone]} rounded-full animate-spin ${className}`}
    />
  )
}
