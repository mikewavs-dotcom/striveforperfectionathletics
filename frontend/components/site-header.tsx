import Image from "next/image";
import Link from "next/link";

import { MobileNav } from "@/components/mobile-nav";
import { NavLinks } from "@/components/nav-links";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-brand-silver bg-black">
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-3 py-2 sm:gap-4 sm:px-4">
        <Link href="/" className="flex min-w-0 items-center gap-2 sm:gap-3">
          <Image
            src="/logo.jpg"
            alt="Strive For Perfection Athletics"
            width={56}
            height={56}
            className="h-10 w-10 shrink-0 rounded-full border border-brand-silver bg-white object-cover sm:h-14 sm:w-14"
            priority
          />
          <span className="min-w-0 leading-tight">
            <span className="block truncate font-display text-base font-extrabold uppercase tracking-wide text-white sm:text-lg">
              Prospect Playground
            </span>
            <span className="hidden text-xs font-semibold uppercase tracking-[0.18em] text-brand-orange sm:block">
              Strive For Perfection Athletics
            </span>
          </span>
        </Link>
        <div className="ml-auto hidden md:block">
          <NavLinks />
        </div>
        <div className="ml-auto md:hidden">
          <MobileNav />
        </div>
      </div>
    </header>
  );
}
