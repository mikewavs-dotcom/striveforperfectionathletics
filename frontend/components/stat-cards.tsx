import { Card, CardContent } from "@/components/ui/card";
import { formatNumber } from "@/lib/labels";
import type { DashboardStats } from "@/lib/types";

export function StatCards({ stats }: { stats: DashboardStats }) {
  const items = [
    { label: "Organizations", value: stats.organization_count },
    { label: "Contacts", value: stats.contact_count },
    { label: "New in last 30 days", value: stats.new_records_last_30_days },
    { label: "Open policy events", value: stats.policy_event_count },
  ];
  return (
    <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label} className="overflow-hidden">
          <div className="h-1 bg-brand-orange" />
          <CardContent className="p-4">
            <p className="font-display text-xs font-bold uppercase tracking-wide text-neutral-500">
              {item.label}
            </p>
            <p className="mt-1 font-display text-3xl font-extrabold text-black">
              {formatNumber(item.value)}
            </p>
          </CardContent>
        </Card>
      ))}
    </section>
  );
}
