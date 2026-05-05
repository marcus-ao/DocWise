import type { Config } from "tailwindcss";

const colorToken = (name: string) => `oklch(from var(--${name}) l c h / <alpha-value>)`

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "var(--font-sans)",
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "PingFang SC",
          "HarmonyOS Sans SC",
          "Microsoft YaHei",
          "sans-serif"
        ],
        mono: [
          "var(--font-mono)",
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace"
        ],
      },
      colors: {
        background: colorToken("background"),
        foreground: colorToken("foreground"),
        card: {
          DEFAULT: colorToken("card"),
          foreground: colorToken("card-foreground"),
        },
        popover: {
          DEFAULT: colorToken("popover"),
          foreground: colorToken("popover-foreground"),
        },
        primary: {
          DEFAULT: colorToken("primary"),
          foreground: colorToken("primary-foreground"),
        },
        secondary: {
          DEFAULT: colorToken("secondary"),
          foreground: colorToken("secondary-foreground"),
        },
        muted: {
          DEFAULT: colorToken("muted"),
          foreground: colorToken("muted-foreground"),
        },
        accent: {
          DEFAULT: colorToken("accent"),
          foreground: colorToken("accent-foreground"),
        },
        destructive: {
          DEFAULT: colorToken("destructive"),
          foreground: colorToken("primary-foreground"),
        },
        border: colorToken("border"),
        input: colorToken("input"),
        ring: colorToken("ring"),
        chart: {
          "1": colorToken("chart-1"),
          "2": colorToken("chart-2"),
          "3": colorToken("chart-3"),
          "4": colorToken("chart-4"),
          "5": colorToken("chart-5"),
        },
        sidebar: {
          DEFAULT: colorToken("sidebar"),
          foreground: colorToken("sidebar-foreground"),
          primary: colorToken("sidebar-primary"),
          "primary-foreground": colorToken("sidebar-primary-foreground"),
          accent: colorToken("sidebar-accent"),
          "accent-foreground": colorToken("sidebar-accent-foreground"),
          border: colorToken("sidebar-border"),
          ring: colorToken("sidebar-ring"),
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
};
export default config;
