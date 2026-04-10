/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#fff0f6',
          100: '#ffe0ed',
          200: '#ffc2db',
          300: '#ff8cb8',
          400: '#ff4d94',
          500: '#FF1493',
          600: '#FF1493',
          700: '#d10f7a',
          800: '#ad0d65',
          900: '#8f0b54',
          950: '#57032f',
        },
        's54-pink': '#FF1493',
        's54-orange': '#FF8C00',
        's54-magenta': '#E91E8C',
        's54-dark': '#0D1117',
        's54-surface': '#161B22',
        's54-border': '#30363D',
        's54-text': '#E6EDF3',
        's54-text-muted': '#8B949E',
      },
      animation: {
        'spin-slow': 'spin 3s linear infinite',
        'pulse-fast': 'pulse 1s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
