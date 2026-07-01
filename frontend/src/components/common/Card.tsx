import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}

export function Card({
  title,
  eyebrow,
  actions,
  children,
  className = "",
  ...rest
}: CardProps) {
  return (
    <div
      className={`rounded-md2 border border-border bg-surface shadow-xs transition-shadow duration-200 ${className}`}
      {...rest}
    >
      {(title || actions || eyebrow) && (
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            {eyebrow && (
              <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted">
                {eyebrow}
              </p>
            )}
            {title && (
              <h3 className="truncate text-[13px] font-semibold text-slate-900">
                {title}
              </h3>
            )}
          </div>
          {actions && <div className="flex flex-none items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-5">{children}</div>
    </div>
  );
}
