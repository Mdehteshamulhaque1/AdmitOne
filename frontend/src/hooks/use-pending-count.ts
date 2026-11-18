import { useSummary } from "@/lib/queries"

export function usePendingCount(): number {
  const { data } = useSummary()
  return data?.pending ?? 0
}