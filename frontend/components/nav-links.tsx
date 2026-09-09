"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/leads", label: "Leads" },
  { href: "/outreach", label: "Outreach" },
  { href: "/policy", label: "Policy" },
  { href: "/sources", label: "Sources" },
];

export function NavLinks({
  className,
  onNavigate,
  tone = "header",
}: {
  className?: string;
  onNavigate?: () => void;
  tone?: "header" | "sheet";
}) {
  const pathname = usePathname();
  return (
    <nav className={cn("flex items-center gap-1", className)}>
      {LINKS.map((link) => {
        const active = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            onClick={onNavigate}
            className={cn(
              "rounded-md px-3 py-1.5 font-display text-sm font-bold uppercase tracking-wide",
              active
                ? "bg-brand-orange text-black"
                : tone === "sheet"
                  ? "text-black hover:bg-brand-orange-light"
                  : "text-white hover:bg-white/10",
            )}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
