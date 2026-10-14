// Inline stroke icons; decorative unless a label is given by the caller.

type IconProps = { size?: number; className?: string };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

export function LogoMark() {
  return (
    <svg width="30" height="30" viewBox="0 0 30 30" fill="none" strokeWidth="2.2" aria-hidden="true">
      <path d="M9.3 13.5 20.7 8.5M9.3 16.5l11.4 5" stroke="var(--border-strong)" />
      <circle cx="6" cy="15" r="3.5" stroke="var(--primary)" />
      <circle cx="24" cy="7" r="3.5" stroke="var(--orange)" />
      <circle cx="24" cy="23" r="3.5" stroke="var(--lime)" />
    </svg>
  );
}

export const SyncIcon = ({ size = 16, className }: IconProps) => (
  <svg {...base(size)} strokeWidth={2} className={className}>
    <path d="M20 11a8 8 0 0 0-14.9-3.9M4 4v4h4M4 13a8 8 0 0 0 14.9 3.9M20 20v-4h-4" />
  </svg>
);

export const PartsIcon = ({ size = 18 }: IconProps) => (
  <svg {...base(size)}>
    <rect x="3" y="3" width="7" height="7" rx="1.5" />
    <rect x="14" y="3" width="7" height="7" rx="1.5" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" />
  </svg>
);

export const BellIcon = ({ size = 18 }: IconProps) => (
  <svg {...base(size)}>
    <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 0 0 3.4 0" />
  </svg>
);

export const PartnersIcon = ({ size = 18 }: IconProps) => (
  <svg {...base(size)}>
    <circle cx="6" cy="12" r="2.5" />
    <circle cx="18" cy="6" r="2.5" />
    <circle cx="18" cy="18" r="2.5" />
    <path d="m8.3 10.9 7.4-3.8M8.3 13.1l7.4 3.8" />
  </svg>
);

export const ClockIcon = ({ size = 18 }: IconProps) => (
  <svg {...base(size)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
);

export const SearchIcon = ({ size = 16 }: IconProps) => (
  <svg {...base(size)} strokeWidth={2}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);

export const CopyIcon = ({ size = 16 }: IconProps) => (
  <svg {...base(size)} strokeWidth={2}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V5a2 2 0 0 1 2-2h10" />
  </svg>
);

export const ChevronIcon = ({ size = 16, className }: IconProps) => (
  <svg {...base(size)} strokeWidth={2.2} className={className}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);

export const CheckIcon = ({ size = 14 }: IconProps) => (
  <svg {...base(size)} strokeWidth={2.5}>
    <path d="m5 12 5 5 9-10" />
  </svg>
);

export const InfoIcon = ({ size = 16 }: IconProps) => (
  <svg {...base(size)} strokeWidth={2} stroke="var(--orange)">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8h.01M11 12h1v5h1" />
  </svg>
);
