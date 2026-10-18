/** Line icons shared by the panel and the view switcher, drawn at 24px with a 2px stroke. */
type IconProps = { className?: string };

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export function ActivityIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M3 12h4l3-8 4 16 3-8h4" />
    </svg>
  );
}

export function RevenueIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </svg>
  );
}

export function PromotionIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z" />
      <circle cx="8" cy="8" r="1.5" />
    </svg>
  );
}

export function AlertIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
    </svg>
  );
}

export function TrendIcon({ className, up }: IconProps & { up: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d={up ? "M6 15l6-6 6 6" : "M6 9l6 6 6-6"} />
    </svg>
  );
}

/** Window with a right side panel; the chevron points the way the panel moves: in to expand, out to collapse. */
export function PanelToggleIcon({ className, expand }: IconProps & { expand: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <path d="M15 4v16" />
      <path d={expand ? "M10 9l-3 3 3 3" : "M7 9l3 3-3 3"} />
    </svg>
  );
}

export function RetryIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />
    </svg>
  );
}

/** Cloud with a slash: the live feed is down. */
export function OfflineIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M7 18h10a4 4 0 0 0 .8-7.9A6 6 0 0 0 7.1 8.4 5 5 0 0 0 7 18zM3 3l18 18" />
    </svg>
  );
}

export function InfoIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </svg>
  );
}

export function LiveIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <circle cx="12" cy="12" r="3" />
      <path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14" />
    </svg>
  );
}

export function SimulationIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3M7 15h10" />
    </svg>
  );
}

export function CheckIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

export function CloseIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

export function ShieldIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6z" />
    </svg>
  );
}

export function MinusIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M6 12h12" />
    </svg>
  );
}

export function CandidateIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M12 2l3 7h7l-5.5 4.5 2 7L12 16l-6.5 4.5 2-7L2 9h7z" />
    </svg>
  );
}

export function KpiIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M3 3v18h18" />
      <path d="M7 16l4-4 4 4 5-6" />
    </svg>
  );
}

export function ChevronDownIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function PlayIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} {...stroke}>
      <path d="M7 5.5v13l11-6.5z" fill="currentColor" />
    </svg>
  );
}
