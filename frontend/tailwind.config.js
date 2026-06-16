import typography from '@tailwindcss/typography'

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // 金融专业风格配色
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#1e40af',
          600: '#1e3a8a',
          700: '#1e3370',
          800: '#172554',
          900: '#0f172a',
        },
        accent: {
          gold: '#d4a843',
          red: '#ef4444',
          green: '#22c55e',
        },
        surface: {
          dark: '#0f1419',
          card: '#1a2332',
          hover: '#243447',
          border: '#2d3f52',
        },
      },
      fontFamily: {
        sans: ['"Inter"', '"Noto Sans SC"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
      },
    },
  },
  plugins: [typography],
}
