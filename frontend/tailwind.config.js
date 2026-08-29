/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Light, airy palette refresh — softer slate for text instead
        // of dark navy, a fresh teal accent instead of dark forest
        // green, and a warmer amber for warnings instead of dark rust.
        ink: "#1E293B",
        paper: "#F8FAFC",
        accent: "#0D9488",
        warn: "#D97706",
      },
    },
  },
  plugins: [],
};
