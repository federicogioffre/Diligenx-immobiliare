import type { Config } from 'tailwindcss'
import typography from '@tailwindcss/typography'

// Every palette the app uses reads from a CSS variable (`--c-<family>-<shade>`,
// space-separated RGB channels defined in globals.css), so the dark theme is a
// second set of values under `.dark` instead of a `dark:` twin on every class.
// `blue-*` is the brand ultramarine scale.
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950] as const
const palette = (family: string) =>
  Object.fromEntries(SHADES.map((s) => [s, `rgb(var(--c-${family}-${s}) / <alpha-value>)`]))

const brand = palette('blue')

const config: Config = {
  darkMode: 'class',
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        slate: palette('slate'),
        red: palette('red'),
        orange: palette('orange'),
        amber: palette('amber'),
        emerald: palette('emerald'),
        indigo: palette('indigo'),
        violet: palette('violet'),
        blue: brand,
        brand,
        // Card and input background: white in light mode, raised dark in dark.
        surface: 'rgb(var(--c-surface) / <alpha-value>)',
        ink: {
          DEFAULT: '#0a0b14',
          900: '#0d0f1c',
          800: '#151829',
          700: '#1f2338',
        },
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        display: ['var(--font-display)', 'ui-serif', 'Georgia', 'serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        lg: '0.625rem',
        xl: '0.875rem',
        '2xl': '1.125rem',
      },
      boxShadow: {
        sm: '0 1px 2px 0 rgb(15 23 42 / 0.05), 0 0 0 1px rgb(15 23 42 / 0.02)',
        DEFAULT: '0 1px 3px 0 rgb(15 23 42 / 0.06), 0 1px 2px -1px rgb(15 23 42 / 0.06)',
        md: '0 4px 12px -2px rgb(15 23 42 / 0.08), 0 2px 4px -2px rgb(15 23 42 / 0.05)',
        lg: '0 12px 28px -6px rgb(15 23 42 / 0.12), 0 4px 8px -4px rgb(15 23 42 / 0.06)',
        xl: '0 24px 48px -12px rgb(15 23 42 / 0.18)',
        glow: '0 0 0 1px rgb(97 112 246 / 0.25), 0 8px 32px -8px rgb(74 85 232 / 0.55)',
        'inner-highlight': 'inset 0 1px 0 0 rgb(255 255 255 / 0.12)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        shimmer: {
          from: { backgroundPosition: '200% 0' },
          to: { backgroundPosition: '-200% 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-6px)' },
        },
        'pulse-ring': {
          '0%': { boxShadow: '0 0 0 0 rgb(97 112 246 / 0.5)' },
          '70%': { boxShadow: '0 0 0 8px rgb(97 112 246 / 0)' },
          '100%': { boxShadow: '0 0 0 0 rgb(97 112 246 / 0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.7s cubic-bezier(0.16, 1, 0.3, 1) both',
        'fade-in': 'fade-in 0.5s ease-out both',
        shimmer: 'shimmer 3s linear infinite',
        float: 'float 6s ease-in-out infinite',
        'pulse-ring': 'pulse-ring 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [typography],
}

export default config
