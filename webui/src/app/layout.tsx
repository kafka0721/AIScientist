import type { Metadata, Viewport } from "next";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { ThemeProvider, ThemedToaster } from "@/providers/ThemeProvider";
import { THEME_STORAGE_KEY } from "@/lib/theme";
import "katex/dist/katex.min.css";
import "./globals.css";

// The landing page contains the configured graph identity. Render it per
// request so clients cannot retain a previous assistant name after upgrades.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Imaging Scientist",
  description:
    "Imaging Scientist research workspace built on DeepAgents and LangGraph.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f9f9f9" },
    { media: "(prefers-color-scheme: dark)", color: "#212121" },
  ],
  colorScheme: "light dark",
};

// Runs before paint so the right theme class is on <html> immediately — no flash
// of the wrong theme. Mirrors ThemeProvider's resolution (default: follow the
// system); ThemeProvider takes over once React mounts. Kept inline + minimal.
const themeScript = `(function(){var k=${JSON.stringify(
  THEME_STORAGE_KEY
)};var t="system";try{t=localStorage.getItem(k)||"system";}catch(_){}var d=t==="dark"||(t!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches);var e=document.documentElement;e.classList.toggle("dark",d);e.style.colorScheme=d?"dark":"light";})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
    >
      <body suppressHydrationWarning>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <NuqsAdapter>
          <ThemeProvider>
            {children}
            <ThemedToaster />
          </ThemeProvider>
        </NuqsAdapter>
      </body>
    </html>
  );
}
