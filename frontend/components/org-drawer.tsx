"use client";

import type { ReactNode } from "react";
import { Star } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { formatDate, humanizeKey, orgTypeLabel, roleLabel, scoreClass } from "@/lib/labels";
import type { OrganizationDetail } from "@/lib/types";

function formatSignal(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    return value === "" ? "—" : value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => formatSignal(item)).join(", ");
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => `${humanizeKey(key)}: ${formatSignal(nested)}`)
      .join("; ");
  }
  return String(value);
}

function ConfidenceStars({ value }: { value: number | null }) {
  const filled = value === null ? 0 : Math.max(0, Math.min(5, Math.round(value * 5)));
  return (
    <span className="inline-flex items-center gap-0.5" title={value === null ? "Unknown" : `${Math.round(value * 100)}%`}>
      {Array.from({ length: 5 }, (_, index) => (
        <Star
          key={index}
          className={`h-3.5 w-3.5 ${index < filled ? "fill-brand-orange text-brand-orange" : "text-brand-silver"}`}
        />
      ))}
    </span>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="font-display text-sm font-bold uppercase tracking-wide text-black">{title}</h3>
      {children}
    </section>
  );
}

export function OrgDrawer({
  detail,
  open,
  pending,
  onOpenChange,
}: {
  detail: OrganizationDetail | null;
  open: boolean;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        {detail === null ? (
          <SheetHeader>
            <SheetTitle>{pending ? "Loading" : "Organization"}</SheetTitle>
            <SheetDescription>
              {pending ? "Loading organization detail…" : "Select a lead."}
            </SheetDescription>
          </SheetHeader>
        ) : (
          <>
            <SheetHeader>
              <SheetTitle>{detail.name}</SheetTitle>
              <SheetDescription>
                {[
                  orgTypeLabel(detail.org_type),
                  [detail.city, detail.state].filter(Boolean).join(", "),
                ]
                  .filter((part) => part !== "")
                  .join(" · ")}
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-6 p-6">
              <Section title="Organization facts">
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                  <dt className="text-neutral-500">EIN</dt>
                  <dd>{detail.ein ?? "—"}</dd>
                  <dt className="text-neutral-500">Phone</dt>
                  <dd>{detail.phone ?? "—"}</dd>
                  <dt className="text-neutral-500">Website</dt>
                  <dd>
                    {detail.website ? (
                      <a className="text-brand-orange-dark underline" href={detail.website} target="_blank" rel="noreferrer">
                        {detail.website}
                      </a>
                    ) : (
                      "—"
                    )}
                  </dd>
                  <dt className="text-neutral-500">Address</dt>
                  <dd>
                    {[detail.street, detail.city, detail.state, detail.postal_code].filter(Boolean).join(", ") || "—"}
                  </dd>
                  <dt className="text-neutral-500">Last verified</dt>
                  <dd>{formatDate(detail.last_verified_at)}</dd>
                  <dt className="text-neutral-500">Revenue</dt>
                  <dd>{detail.annual_revenue ?? "—"}</dd>
                </dl>
              </Section>

              <Section title="Verify sources">
                {(detail.source_urls ?? []).length === 0 ? (
                  <p className="text-sm text-neutral-500">No source URLs.</p>
                ) : (
                  <ul className="space-y-2">
                    {(detail.source_urls ?? []).map((url) => (
                      <li key={url}>
                        <a
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center rounded-md bg-brand-orange px-3 py-2 text-sm font-semibold text-black hover:bg-brand-orange-dark hover:text-white"
                        >
                          Verify source
                          <span className="ml-2 max-w-[18rem] truncate font-normal text-neutral-800">{url}</span>
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section title="Contacts">
                {detail.contacts.length === 0 ? (
                  <p className="text-sm text-neutral-500">No contacts.</p>
                ) : (
                  <ul className="space-y-3">
                    {detail.contacts.map((contact) => (
                      <li key={contact.id} className="rounded-md border border-brand-silver p-3 text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <p className="font-semibold">{contact.full_name ?? "Unnamed"}</p>
                          <ConfidenceStars value={contact.confidence} />
                        </div>
                        <p className="capitalize text-neutral-600">{roleLabel(contact.role)}</p>
                        {contact.title_raw ? <p className="text-neutral-500">{contact.title_raw}</p> : null}
                        <p>{contact.email ?? "No email"}</p>
                        <p>{contact.phone ?? "No phone"}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section title="Scores">
                {detail.scores.length === 0 ? (
                  <p className="text-sm text-neutral-500">Not scored yet.</p>
                ) : (
                  <ul className="space-y-4">
                    {detail.scores.map((score) => (
                      <li key={score.id} className="space-y-2 rounded-md border border-brand-silver p-3">
                        <div className="flex items-center gap-2">
                          <span className="font-display text-sm font-bold uppercase">{score.offer}</span>
                          <Badge className={scoreClass(score.score)}>{score.score}</Badge>
                        </div>
                        <p className="text-sm">{score.rationale}</p>
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                          {Object.entries(score.signals).map(([key, value]) => (
                            <div key={key} className="contents">
                              <dt className="text-neutral-500">{humanizeKey(key)}</dt>
                              <dd>{formatSignal(value)}</dd>
                            </div>
                          ))}
                        </dl>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section title="Policy events">
                {detail.policy_events.length === 0 ? (
                  <p className="text-sm text-neutral-500">No linked policy events.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {detail.policy_events.map((event) => (
                      <li key={event.id} className="rounded-md border border-brand-silver p-3">
                        <p className="font-semibold">{event.jurisdiction}</p>
                        <p>{event.summary ?? event.event_type}</p>
                        <a className="text-brand-orange-dark underline" href={event.source_url} target="_blank" rel="noreferrer">
                          Verify source
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section title="Sponsors">
                {detail.sponsors.length === 0 ? (
                  <p className="text-sm text-neutral-500">No linked sponsors.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {detail.sponsors.map((sponsor) => (
                      <li key={sponsor.id}>
                        <span className="font-semibold">{sponsor.brand_name}</span>
                        <a className="ml-2 text-brand-orange-dark underline" href={sponsor.detected_on_url} target="_blank" rel="noreferrer">
                          Verify source
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
