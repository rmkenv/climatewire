/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ['var(--font-display)', 'serif'],
        mono:    ['var(--font-mono)', 'monospace'],
        body:    ['var(--font-body)', 'sans-serif'],
      },
      colors: {
        surface:  'var(--surface)',
        border:   'var(--border)',
        muted:    'var(--muted)',
        accent:   'var(--accent)',
        ink:      'var(--ink)',
      },
    },
  },
  plugins: [],
}
