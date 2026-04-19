/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
        sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'],
      },
      colors: {
        bg: {
          primary:   '#090b10',
          secondary: '#0d1017',
          card:      '#111520',
          hover:     '#161b27',
          border:    'rgba(255,255,255,0.06)',
          'border-mid': 'rgba(255,255,255,0.12)',
        },
        accent: {
          blue:   '#4f9cf9',
          green:  '#34d399',
          amber:  '#fbbf24',
          red:    '#f87171',
          purple: '#a78bfa',
          teal:   '#2dd4bf',
          coral:  '#fb7185',
        },
        text: {
          primary:   '#e2e8f0',
          secondary: '#7c8599',
          muted:     '#434a5c',
        }
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.25s ease-out',
      },
      keyframes: {
        fadeIn: { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(6px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
      }
    },
  },
  plugins: [],
}
