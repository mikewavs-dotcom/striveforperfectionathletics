import type { ReactNode } from "react";
import { Barlow_Condensed, Inter } from "next/font/google";
import type { Metadata } from "next";

import { SiteHeader } from "@/components/site-header";
import "./globals.css";

const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

const display = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "Prospect Playground",
  description: "Lead intelligence for Strive For Perfection Athletics",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${sans.variable} ${display.variable} min-h-screen bg-neutral-50 font-sans text-black antialiased`}>
        <SiteHeader />
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
