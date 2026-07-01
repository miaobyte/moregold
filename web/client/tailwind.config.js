/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        panel:  '#1e222d',
        border: '#2a2e39',
        input:  '#2a2e39',
        muted:  '#787b86',
        fg:     '#d1d4dc',
        gold:   '#f0c040',
      },
    },
  },
  plugins: [],
};
