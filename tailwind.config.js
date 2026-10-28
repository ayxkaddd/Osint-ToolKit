// Build: npm run build:css  (writes static/css/tailwind.css, which is committed)
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./templates/**/*.html", "./static/js/**/*.js"],
  safelist: [
    // dashboard.js: text-${module.icon_color}-500 (colors come from resources.json)
    { pattern: /^text-(red|pink|purple|blue|green|yellow|orange|indigo|cyan|teal|emerald|gray|white|violet|rose|sky|lime|amber|fuchsia|slate)-(400|500)$/ },
    // username.js: ml-${indent * 4}
    { pattern: /^ml-(0|4|8|12|16|20|24)$/ },
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
}
