import { Component, type ErrorInfo, type ReactNode } from "react"
import { AlertTriangle, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/Button"

interface Props {
  children: ReactNode
  /** Compact rendering for boundaries nested inside the console shell. */
  inline?: boolean
}

interface State {
  error: Error | null
}

/**
 * Last line of defence against a render-time crash. A thrown error inside a
 * page should take down that page, not the whole console: the shell wraps
 * the outlet in an inline boundary and the root wraps everything.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (import.meta.env.DEV) {
      console.error("Unhandled render error", error, info.componentStack)
    }
  }

  reset = () => this.setState({ error: null })

  render() {
    if (!this.state.error) return this.props.children
    const chunkFailed = /Loading chunk|dynamically imported module|Failed to fetch/i.test(
      this.state.error.message,
    )
    const body = (
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <span className="flex size-14 items-center justify-center rounded-2xl bg-danger-soft text-danger">
          <AlertTriangle className="size-6" />
        </span>
        <div>
          <h2 className="text-lg font-semibold">
            {chunkFailed ? "A newer version is available" : "Something went wrong"}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {chunkFailed
              ? "The app was updated while you were using it. Reload to get the latest version."
              : "This screen hit an unexpected error. Your data is safe; try again or reload the page."}
          </p>
          {import.meta.env.DEV && (
            <pre className="mt-3 max-h-40 overflow-auto rounded-lg bg-surface-2 p-3 text-left text-xs text-danger">
              {this.state.error.message}
            </pre>
          )}
        </div>
        <div className="flex gap-2">
          {!chunkFailed && (
            <Button variant="outline" onClick={this.reset}>
              Try again
            </Button>
          )}
          <Button onClick={() => window.location.reload()}>
            <RefreshCw className="size-4" /> Reload
          </Button>
        </div>
      </div>
    )
    if (this.props.inline) {
      return <div className="card-surface flex justify-center p-10">{body}</div>
    }
    return <div className="flex min-h-screen items-center justify-center bg-background p-6">{body}</div>
  }
}
