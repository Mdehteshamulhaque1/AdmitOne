import { useEffect, useState } from "react"
import { Search, X } from "lucide-react"
import { Input } from "@/components/ui/Input"
import { cn } from "@/lib/utils"

interface SearchInputProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  /** Debounce in ms before `onChange` fires (0 = immediate). */
  delay?: number
  autoFocus?: boolean
}

export function SearchInput({ value, onChange, placeholder = "Search…", className, delay = 300, autoFocus }: SearchInputProps) {
  const [draft, setDraft] = useState(value)

  useEffect(() => {
    setDraft(value)
  }, [value])

  useEffect(() => {
    if (draft === value) return
    const t = setTimeout(() => onChange(draft), delay)
    return () => clearTimeout(t)
  }, [draft, delay, onChange, value])

  return (
    <div className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onChange(draft)
          if (e.key === "Escape") {
            setDraft("")
            onChange("")
          }
        }}
        placeholder={placeholder}
        className="pl-9 pr-9"
        autoFocus={autoFocus}
        aria-label={placeholder}
      />
      {draft && (
        <button
          type="button"
          onClick={() => {
            setDraft("")
            onChange("")
          }}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground transition hover:bg-hover hover:text-foreground"
          aria-label="Clear search"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  )
}
