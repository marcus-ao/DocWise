import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/sidebar";
import { BackendStatusProvider } from "@/components/providers/backend-status-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "DocWise",
  description: "Enterprise Developer Knowledge Workflow Agent",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased bg-background text-foreground transition-colors duration-500 h-screen w-screen overflow-hidden flex`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange={false}
        >
          <BackendStatusProvider>
            <TooltipProvider>
              <Sidebar />
              <main className="flex-1 flex min-w-0 flex-col bg-muted/20 transition-colors duration-500 dark:bg-background">
                {children}
              </main>
            </TooltipProvider>
          </BackendStatusProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
