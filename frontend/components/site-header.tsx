import Image from "next/image";
import Link from "next/link";

import { NavLinks } from "@/components/nav-links";

export function SiteHeader() {
  return (
    <header className="border-b border-brand-silver bg-black">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2">
        <Link href="/" className="flex items-center gap-3">
          <Image
            src="/logo.jpg"
            alt="Strive For Perfection Athletics"
            width={56}
            height={56}
            className="h-14 w-14 rounded-full border border-brand-silver bg-white object-cover"
            priority
          />
          <span className="leading-tight">
            <span className="block font-display text-lg font-extrabold uppercase tracking-wide text-white">
              Prospect Playground
            </span>
            <span className="block text-xs font-semibold uppercase tracking-[0.18em] text-brand-orange">
              Strive For Perfection Athletics
            </span>
          </span>
        </Link>
        <div className="ml-auto">
          <NavLinks />
        </div>
      </div>
    </header>
  );
}
