import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  isLoading?: boolean;
  icon?: ReactNode;
}

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-accent text-white border border-accent shadow-xs hover:bg-accent-600 hover:shadow-card active:bg-accent-700",
  secondary:
    "bg-white text-slate-700 border border-border shadow-xs hover:bg-surfaceHover hover:border-slate-300 active:bg-slate-100",
  ghost:
    "bg-transparent text-muted border border-transparent hover:text-slate-900 hover:bg-surfaceHover active:bg-slate-200/60",
  danger:
    "bg-danger/10 text-danger border border-danger/15 hover:bg-danger/15 active:bg-danger/20",
};

const sizeClasses: Record<Size, string> = {
  sm: "text-xs px-3 py-1.5 gap-1.5",
  md: "text-sm px-4 py-2.5 gap-2",
};

export function Button({
  variant = "secondary",
  size = "md",
  isLoading = false,
  icon,
  children,
  className = "",
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-md2 font-medium
        transition-all duration-150 ease-out disabled:opacity-50 disabled:cursor-not-allowed
        disabled:hover:shadow-none whitespace-nowrap select-none
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/30
        ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      disabled={disabled || isLoading}
      {...rest}
    >
      {isLoading ? (
        <span className="h-3.5 w-3.5 flex-none rounded-full border-2 border-current border-t-transparent animate-spin" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}
