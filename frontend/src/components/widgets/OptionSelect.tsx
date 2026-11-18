import { useEffect, useState } from "react"
import { Input } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { OTHER_VALUE, type Option } from "@/lib/student-options"

interface OptionSelectProps {
  id?: string
  value: string
  onChange: (value: string) => void
  options: readonly Option[]
  placeholder?: string
  disabled?: boolean
  /** Append an "Other…" choice that reveals a text box for a custom value. */
  allowOther?: boolean
  otherPlaceholder?: string
  "aria-invalid"?: boolean
}

/**
 * A dropdown whose value is plain text. With `allowOther`, picking "Other…"
 * reveals an input so a visitor whose university/state is not listed can
 * still type it; a stored value not in `options` is shown the same way.
 */
export function OptionSelect({
  id,
  value,
  onChange,
  options,
  placeholder = "Select…",
  disabled,
  allowOther = false,
  otherPlaceholder = "Type your answer",
}: OptionSelectProps) {
  const inList = options.some((o) => o.value === value)
  const [custom, setCustom] = useState(() => Boolean(allowOther && value && !inList))

  useEffect(() => {
    if (value && !inList && allowOther) setCustom(true)
    if (!value && custom && inList) setCustom(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  const selectValue = custom ? OTHER_VALUE : inList ? value : ""

  return (
    <div className="space-y-2">
      <Select
        value={selectValue || undefined}
        disabled={disabled}
        onValueChange={(v) => {
          if (v === OTHER_VALUE) {
            setCustom(true)
            onChange("")
            return
          }
          setCustom(false)
          onChange(v)
        }}
      >
        <SelectTrigger id={id} aria-label={placeholder}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
          {allowOther && <SelectItem value={OTHER_VALUE}>Other…</SelectItem>}
        </SelectContent>
      </Select>
      {custom && (
        <Input
          id={id ? `${id}-other` : undefined}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={otherPlaceholder}
          autoFocus
        />
      )}
    </div>
  )
}
