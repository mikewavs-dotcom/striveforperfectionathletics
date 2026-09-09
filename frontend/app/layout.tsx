import type { ReactNode } from "react";
import { Barlow_Condensed, Inter } from "next/font/google";
import type { Metadata, Viewport } from "next";

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

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${sans.variable} ${display.variable} min-h-screen overflow-x-hidden bg-neutral-50 font-sans text-black antialiased`}>
        <SiteHeader />
        <main className="mx-auto max-w-7xl px-3 py-4 sm:px-4 sm:py-6">{children}</main>
      </body>
    </html>
  );
}
