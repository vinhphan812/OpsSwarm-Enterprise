import { motion } from "framer-motion";
import { useRef, type KeyboardEvent, type ReactNode } from "react";
import "./commerce.css";

export type SegmentOption<T extends string> = {
  value: T;
  label: string;
  icon?: ReactNode;
  /** Small count after the label, such as how many promotions have a status. */
  badge?: number;
  /** A small dot that asks for attention; the text says why, after the label in its name and tooltip. */
  dot?: string;
  /** Shown but not pickable, by click or by arrow key. */
  disabled?: boolean;
};

type SegmentedProps<T extends string> = {
  label: string;
  options: readonly SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Unique per control on screen: the selected thumb slides between options under this id. */
  layoutId: string;
  /** `glass` floats over the 3D view, `panel` sits in the side panel, `chips` wraps onto several lines. */
  variant?: "glass" | "panel" | "chips";
};

const THUMB_SLIDE = { type: "spring", stiffness: 520, damping: 40 } as const;

/** A radio group drawn as one pill: arrow keys move the choice and an accent thumb slides to it. */
export function Segmented<T extends string>({ label, options, value, onChange, layoutId, variant = "panel" }: SegmentedProps<T>) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const index = options.findIndex((option) => option.value === value);

  const onKeyDown = (event: KeyboardEvent) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    let next = index;
    do next = (next + step + options.length) % options.length;
    while (options[next].disabled && next !== index);
    if (next === index) return;
    onChange(options[next].value);
    buttons.current[next]?.focus();
  };

  return (
    <div role="radiogroup" aria-label={label} className={`segmented segmented-${variant}`} onKeyDown={onKeyDown}>
      {options.map((option, i) => {
        const selected = option.value === value;
        const name = option.dot ? `${option.label} (${option.dot})` : option.label;
        return (
          <button
            key={option.value}
            ref={(node) => {
              buttons.current[i] = node;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={name}
            // The glass switch hides its labels on small screens; elsewhere the label is on show.
            title={variant === "glass" || option.dot ? name : undefined}
            tabIndex={selected ? 0 : -1}
            disabled={option.disabled}
            className="segmented-option"
            data-selected={selected}
            onClick={() => onChange(option.value)}
          >
            {selected ? <motion.span layoutId={layoutId} className="segmented-thumb" transition={THUMB_SLIDE} /> : null}
            <span className="segmented-content">
              {option.icon}
              <span className="segmented-label">{option.label}</span>
              {option.badge === undefined ? null : <span className="segmented-badge">{option.badge}</span>}
              {option.dot ? <span className="segmented-dot" aria-hidden /> : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}
