"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Fragment } from "react";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-muted-foreground">
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        return (
          <Fragment key={item.label}>
            {index > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
            {item.href && !isLast ? (
              <Link href={item.href} className="transition-colors hover:text-foreground">
                {item.label}
              </Link>
            ) : (
              <span className={isLast ? "font-medium text-foreground" : undefined}>{item.label}</span>
            )}
          </Fragment>
        );
      })}
    </nav>
  );
}
