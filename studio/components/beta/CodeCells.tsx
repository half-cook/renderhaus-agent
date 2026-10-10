"use client";

import { useRef } from "react";

/** Six single-digit cells. Typing advances, Backspace steps back, and a pasted code fills every cell. */
export function CodeCells({ value, onChange, invalid, disabled, label }: {
  value: string;
  onChange: (next: string) => void;
  invalid?: boolean;
  disabled?: boolean;
  label: string;
}) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const cells = Array.from({ length: 6 }, (_, index) => value[index] ?? "");
  const focus = (index: number) => refs.current[Math.max(0, Math.min(5, index))]?.focus();
  return (
    <div className="rh-cells" role="group" aria-label={label}>
      {cells.map((digit, index) => (
        <input
          key={index}
          ref={(node) => { refs.current[index] = node; }}
          className="rh-cell"
          inputMode="numeric"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          maxLength={1}
          value={digit}
          disabled={disabled}
          aria-label={`${label}, digit ${index + 1}`}
          aria-invalid={invalid || undefined}
          data-invalid={invalid || undefined}
          onChange={(event) => {
            const typed = event.target.value.replace(/\D/g, "");
            if (!typed) return;
            const next = value.slice(0, index) + typed[typed.length - 1] + value.slice(index + 1);
            onChange(next.slice(0, 6));
            focus(index + 1);
          }}
          onKeyDown={(event) => {
            if (event.key === "Backspace") {
              event.preventDefault();
              onChange(value.slice(0, index) + value.slice(index + 1));
              focus(digit ? index : index - 1);
            }
            if (event.key === "ArrowLeft") focus(index - 1);
            if (event.key === "ArrowRight") focus(index + 1);
          }}
          onPaste={(event) => {
            const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
            if (!pasted) return;
            event.preventDefault();
            onChange(pasted);
            focus(pasted.length);
          }}
        />
      ))}
    </div>
  );
}
