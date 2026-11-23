import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react"
import { Check, ChevronDown, X } from "lucide-react"
import { Input } from "@/components/ui/Input"
import { OTHER_VALUE, type Option } from "@/lib/student-options"
import { cn } from "@/lib/utils"

export interface SearchableOption extends Option {
  description?: string
  disabled?: boolean
}

interface BaseProps {
  id?: string
  options: readonly SearchableOption[]
  placeholder?: string
  disabled?: boolean
  emptyMessage?: string
  className?: string
  "aria-invalid"?: boolean
  "aria-label"?: string
  onQueryChange?: (query: string) => void
}

interface SearchableSelectProps extends BaseProps {
  value: string
  onChange: (value: string) => void
  allowOther?: boolean
  otherPlaceholder?: string
}

function matches(option: SearchableOption, query: string) {
  if (!query) return true
  const q = query.toLowerCase()
  return `${option.label} ${option.description ?? ""} ${option.value}`.toLowerCase().includes(q)
}

function otherOption(query: string): SearchableOption {
  const trimmed = query.trim()
  return {
    value: OTHER_VALUE,
    label: trimmed ? `Use “${trimmed}”` : "Other…",
    description: "Type your own value",
  }
}

export function SearchableSelect({
  id,
  value,
  onChange,
  options,
  placeholder = "Select…",
  disabled,
  allowOther = false,
  otherPlaceholder = "Type your answer",
  emptyMessage = "No matches found",
  className,
  onQueryChange,
  "aria-invalid": ariaInvalid,
  "aria-label": ariaLabel,
}: SearchableSelectProps) {
  const listId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [activeIndex, setActiveIndex] = useState(0)
  const inList = options.some((o) => o.value === value)
  const [custom, setCustom] = useState(() => Boolean(allowOther && value && !inList))

  useEffect(() => {
    if (value && !inList && allowOther) setCustom(true)
    if ((!value || inList) && custom) setCustom(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, inList, allowOther])

  const allOptions = useMemo(() => {
    const base = options.filter((o) => o.value !== OTHER_VALUE)
    return allowOther ? [...base, otherOption(query)] : base
  }, [allowOther, options, query])

  const visibleOptions = useMemo(() => allOptions.filter((o) => matches(o, query)), [allOptions, query])

  useEffect(() => setActiveIndex(0), [query, visibleOptions.length])

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
        setQuery("")
        onQueryChange?.("")
      }
    }
    document.addEventListener("mousedown", close)
    return () => document.removeEventListener("mousedown", close)
  }, [open, onQueryChange])

  const selected = options.find((o) => o.value === value)
  const displayValue = open ? query : custom ? value : selected?.label ?? ""

  const openList = () => {
    if (disabled) return
    setOpen(true)
    setQuery("")
    setActiveIndex(0)
    onQueryChange?.("")
  }

  const select = (option: SearchableOption) => {
    if (option.disabled) return
    if (allowOther && option.value === OTHER_VALUE) {
      setCustom(true)
      onChange(query.trim())
    } else {
      setCustom(false)
      onChange(option.value)
    }
    setOpen(false)
    setQuery("")
    onQueryChange?.("")
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "Enter") {
        event.preventDefault()
        openList()
      }
      return
    }
    if (event.key === "ArrowDown") {
      event.preventDefault()
      setActiveIndex((i) => Math.min(i + 1, visibleOptions.length - 1))
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, 0))
    } else if (event.key === "Enter") {
      event.preventDefault()
      const option = visibleOptions[activeIndex]
      if (option) select(option)
    } else if (event.key === "Escape") {
      setOpen(false)
      setQuery("")
      onQueryChange?.("")
    }
  }

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <div className="relative">
        <Input
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={open && visibleOptions[activeIndex] ? `${listId}-${activeIndex}` : undefined}
          aria-invalid={ariaInvalid}
          aria-label={ariaLabel}
          autoComplete="off"
          disabled={disabled}
          placeholder={placeholder}
          value={displayValue}
          onFocus={openList}
          onClick={openList}
          onChange={(e) => {
            const next = e.target.value
            if (custom) {
              onChange(next)
              return
            }
            setQuery(next)
            setOpen(true)
            setActiveIndex(0)
            onQueryChange?.(next)
          }}
          onKeyDown={onKeyDown}
          className="pr-9"
        />
        <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      </div>
      {open && !disabled && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-border bg-popover p-1.5 text-foreground shadow-lift animate-scale-in"
        >
          {visibleOptions.length === 0 ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">{emptyMessage}</div>
          ) : (
            visibleOptions.map((option, index) => {
              const active = index === activeIndex
              const selectedOption = !custom && option.value === value
              return (
                <button
                  key={option.value}
                  id={`${listId}-${index}`}
                  type="button"
                  role="option"
                  aria-selected={selectedOption}
                  aria-disabled={option.disabled}
                  disabled={option.disabled}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => select(option)}
                  className={cn(
                    "flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors",
                    active ? "bg-hover" : "hover:bg-hover",
                    option.disabled && "pointer-events-none opacity-50",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{option.label}</span>
                    {option.description && <span className="block text-xs text-muted-foreground">{option.description}</span>}
                  </span>
                  {selectedOption && <Check className="mt-0.5 size-4 shrink-0 text-primary" />}
                </button>
              )
            })
          )}
        </div>
      )}
      {custom && (
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={otherPlaceholder}
          aria-label={otherPlaceholder}
          className="mt-2"
          autoFocus
        />
      )}
    </div>
  )
}

interface SearchableMultiSelectProps extends BaseProps {
  value: string[]
  onChange: (value: string[]) => void
}

export function SearchableMultiSelect({
  id,
  value,
  onChange,
  options,
  placeholder = "Search and select…",
  disabled,
  emptyMessage = "No matches found",
  className,
  onQueryChange,
  "aria-invalid": ariaInvalid,
  "aria-label": ariaLabel,
}: SearchableMultiSelectProps) {
  const listId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [activeIndex, setActiveIndex] = useState(0)

  const allOptions = useMemo(() => [...options, otherOption(query)], [options, query])
  const visibleOptions = useMemo(() => allOptions.filter((o) => matches(o, query)), [allOptions, query])

  useEffect(() => setActiveIndex(0), [query, visibleOptions.length])

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
        setQuery("")
        onQueryChange?.("")
      }
    }
    document.addEventListener("mousedown", close)
    return () => document.removeEventListener("mousedown", close)
  }, [open, onQueryChange])

  const toggle = (option: SearchableOption) => {
    if (option.disabled) return
    const nextValue = option.value === OTHER_VALUE ? query.trim() : option.value
    if (!nextValue) return
    onChange(value.includes(nextValue) ? value.filter((v) => v !== nextValue) : [...value, nextValue])
    setQuery("")
    onQueryChange?.("")
    setActiveIndex(0)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!open && (event.key === "ArrowDown" || event.key === "Enter")) {
      event.preventDefault()
      setOpen(true)
      return
    }
    if (!open) return
    if (event.key === "ArrowDown") {
      event.preventDefault()
      setActiveIndex((i) => Math.min(i + 1, visibleOptions.length - 1))
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, 0))
    } else if (event.key === "Enter") {
      event.preventDefault()
      const option = visibleOptions[activeIndex]
      if (option) toggle(option)
    } else if (event.key === "Escape") {
      setOpen(false)
      setQuery("")
      onQueryChange?.("")
    }
  }

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg border border-input bg-secondary/60 px-2.5 py-1.5 shadow-sm focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/40">
        {value.map((item) => (
          <span key={item} className="inline-flex items-center gap-1 rounded-md bg-primary-soft px-2 py-1 text-xs font-medium text-primary">
            {item}
            <button type="button" onClick={() => onChange(value.filter((v) => v !== item))} aria-label={`Remove ${item}`} className="rounded-sm hover:text-foreground">
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={open && visibleOptions[activeIndex] ? `${listId}-${activeIndex}` : undefined}
          aria-invalid={ariaInvalid}
          aria-label={ariaLabel}
          autoComplete="off"
          disabled={disabled}
          placeholder={value.length === 0 ? placeholder : "Add another…"}
          value={query}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
            onQueryChange?.(e.target.value)
          }}
          onKeyDown={onKeyDown}
          className="min-w-28 flex-1 bg-transparent py-0.5 text-sm text-foreground outline-none placeholder:text-muted-foreground/70 disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>
      {open && !disabled && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-border bg-popover p-1.5 text-foreground shadow-lift animate-scale-in"
        >
          {visibleOptions.length === 0 ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">{emptyMessage}</div>
          ) : (
            visibleOptions.map((option, index) => (
              <button
                key={option.value}
                id={`${listId}-${index}`}
                type="button"
                role="option"
                aria-selected={value.includes(option.value)}
                aria-disabled={option.disabled}
                disabled={option.disabled}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => toggle(option)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors",
                  index === activeIndex ? "bg-hover" : "hover:bg-hover",
                  option.disabled && "pointer-events-none opacity-50",
                )}
              >
                <span className={cn("flex size-4 items-center justify-center rounded border border-border", value.includes(option.value) && "border-primary bg-primary text-primary-foreground")}>
                  {value.includes(option.value) && <Check className="size-3" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium">{option.label}</span>
                  {option.description && <span className="block text-xs text-muted-foreground">{option.description}</span>}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
