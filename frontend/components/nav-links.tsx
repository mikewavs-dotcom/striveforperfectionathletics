"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/leads", label: "Leads" },
  { href: "/policy", label: "Policy" },
  { href: "/sources", label: "Sources" },
];

export function NavLinks() {
  const pathname = usePathname();
  return (
    <nav className="flex items-center gap-1">
      {LINKS.map((link) => {
        const active = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "rounded-md px-3 py-1.5 font-display text-sm font-bold uppercase tracking-wide",
              active ? "bg-brand-orange text-black" : "text-white hover:bg-white/10",
            )}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
