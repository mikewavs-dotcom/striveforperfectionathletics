"use client";

import { useState } from "react";
import { Menu } from "lucide-react";

import { NavLinks } from "@/components/nav-links";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

export function MobileNav() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="inline-flex h-11 w-11 items-center justify-center rounded-md text-white hover:bg-white/10"
        aria-label="Open menu"
        onClick={() => setOpen(true)}
      >
        <Menu className="h-6 w-6" />
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="left-0 right-auto w-[min(100%,18rem)] max-w-[18rem] border-l-0 border-r border-brand-silver">
          <SheetHeader>
            <SheetTitle>Menu</SheetTitle>
          </SheetHeader>
          <NavLinks
            tone="sheet"
            onNavigate={() => setOpen(false)}
            className="flex-col items-stretch gap-1 p-3 [&>a]:min-h-11 [&>a]:px-3 [&>a]:py-3"
          />
        </SheetContent>
      </Sheet>
    </>
  );
}
