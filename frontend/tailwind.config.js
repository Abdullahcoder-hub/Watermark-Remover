/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#14213D",
        paper: "#FBFAF8",
        accent: "#2F6F5E",
        warn: "#B3541E",
      },
    },
  },
  plugins: [],
};
