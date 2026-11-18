import { RefreshCw } from "lucide-react"
import { Alert } from "@/components/ui/Alert"
import { Button } from "@/components/ui/Button"

export function QueryErrorState({
  message = "Couldn't load data",
  retry,
}: {
  message?: string
  retry?: () => void
}) {
  return (
    <Alert variant="danger" className="items-center">
      <span className="flex-1">{message}</span>
      {retry && (
        <Button variant="ghost" size="sm" onClick={retry}>
          <RefreshCw className="size-3.5" /> Retry
        </Button>
      )}
    </Alert>
  )
}