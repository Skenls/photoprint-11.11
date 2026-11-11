type IconProps = {
  size?: number;
  className?: string;
};

function svgProps({ size = 18, className }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
    "aria-hidden": true,
  };
}

export function IconDashboard(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="4" rx="1.5" />
      <rect x="14" y="11" width="7" height="10" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

export function IconInbox(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 5.5h16v11H9l-5 4v-15Z" />
      <path d="M8.5 10h7M8.5 13h4" />
    </svg>
  );
}

export function IconUsers(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 19c.6-3.2 2.7-5 5.5-5s4.9 1.8 5.5 5" />
      <path d="M16 5.6a3 3 0 0 1 0 5.8M17.5 14.4c1.7.5 2.8 2.1 3.2 4.6" />
    </svg>
  );
}

export function IconSpark(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 2.8c.7 4.7 2.5 6.5 7.2 7.2-4.7.7-6.5 2.5-7.2 7.2-.7-4.7-2.5-6.5-7.2-7.2 4.7-.7 6.5-2.5 7.2-7.2Z" />
      <path d="M19 15.5c.3 1.9 1 2.6 2.9 2.9-1.9.3-2.6 1-2.9 2.9-.3-1.9-1-2.6-2.9-2.9 1.9-.3 2.6-1 2.9-2.9Z" />
    </svg>
  );
}

export function IconShield(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 3 5 6v5.5c0 4.4 2.8 7.6 7 9.5 4.2-1.9 7-5.1 7-9.5V6l-7-3Z" />
      <path d="m9.3 12 1.9 1.9 3.7-3.8" />
    </svg>
  );
}

export function IconSearch(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="10.8" cy="10.8" r="6.3" />
      <path d="m15.5 15.5 4.2 4.2" />
    </svg>
  );
}

export function IconSend(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="m4 4.5 16 7.5-16 7.5 2.2-7.5L4 4.5Z" />
      <path d="M6.2 12H20" />
    </svg>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function IconClock(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

export function IconArrow(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M5 12h14M14 7l5 5-5 5" />
    </svg>
  );
}

export function IconLogout(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M14 8V5H5v14h9v-3" />
      <path d="M10 12h10M17 9l3 3-3 3" />
    </svg>
  );
}

export function IconAlert(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 3 2.8 20h18.4L12 3Z" />
      <path d="M12 9v5M12 17.2v.2" />
    </svg>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  );
}

export function IconBot(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <rect x="4" y="7" width="16" height="12" rx="4" />
      <path d="M12 3v4M8.5 12.5v1M15.5 12.5v1M9 16.5h6" />
    </svg>
  );
}

export function IconClose(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="m6 6 12 12M18 6 6 18" />
    </svg>
  );
}

export function IconRefresh(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 4v7h-7" />
    </svg>
  );
}

export function IconChart(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </svg>
  );
}

export function IconUser(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c.8-4 4-6 8-6s7.2 2 8 6" />
    </svg>
  );
}

export function IconPhone(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M6.5 3.5 9 8l-2 1.6c.8 2.2 2.2 3.6 4.4 4.4L13 12l4.5 2.5-.7 3.2c-4.3.7-8-1-10.4-3.4S3.6 7.8 4.3 3.5h2.2Z" />
    </svg>
  );
}

export function IconMail(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <path d="m4 7 8 6 8-6" />
    </svg>
  );
}

export function IconGlobe(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.3 2.3 3.4 5.1 3.4 8.5s-1.1 6.2-3.4 8.5c-2.3-2.3-3.4-5.1-3.4-8.5S9.7 5.8 12 3.5Z" />
    </svg>
  );
}
