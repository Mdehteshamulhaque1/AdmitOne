import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter } from "react-router-dom"
import { Toaster } from "sonner"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { TooltipProvider } from "@/components/ui/Tooltip"
import { AuthProvider } from "@/lib/auth"
import { ThemeProvider, useTheme } from "@/lib/theme"
import App from "@/App"
import "@/index.css"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      retry: (failureCount, error) => {
        // Never hammer the API on auth/permission errors; retry transient ones once.
        const status = (error as { status?: number }).status
        if (status && status >= 400 && status < 500) return false
        return failureCount < 1
      },
      refetchOnWindowFocus: true,
    },
  },
})

function ThemedToaster() {
  const { resolved } = useTheme()
  return (
    <Toaster
      theme={resolved}
      position="bottom-right"
      closeButton
      richColors
      toastOptions={{
        className: "font-sans",
        style: {
          background: "var(--sg-popover)",
          border: "1px solid var(--sg-border)",
          color: "var(--sg-fg)",
          boxShadow: "var(--sg-shadow-lift)",
        },
      }}
    />
  )
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <TooltipProvider delayDuration={200}>
              <AuthProvider>
                <App />
                <ThemedToaster />
              </AuthProvider>
            </TooltipProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </ErrorBoundary>
    </ThemeProvider>
  </StrictMode>,
)
