interface BrandLogoProps {
  className?: string;
}

export function BrandLogo({ className }: BrandLogoProps) {
  return (
    <span className={className ? `brand-lockup ${className}` : "brand-lockup"}>
      <svg aria-hidden="true" className="brand-mark" fill="none" viewBox="0 0 40 40">
        <rect fill="#896E54" height="40" rx="12" width="40" />
        <path d="M11 29V13.5A4.5 4.5 0 0 1 15.5 9h9A4.5 4.5 0 0 1 29 13.5V29" stroke="#F7F5F0" strokeLinecap="round" strokeWidth="3.5" />
        <path d="M15 29h10M20 14.5v10" stroke="#F7F5F0" strokeLinecap="round" strokeWidth="3.5" />
      </svg>
      <span>BuyByFit</span>
    </span>
  );
}
