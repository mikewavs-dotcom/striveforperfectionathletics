export async function POST(
  _request: Request,
  context: { params: { id: string } },
): Promise<Response> {
  const apiUrl = process.env.API_URL;
  if (!apiUrl) {
    return new Response("API_URL is not set", { status: 500 });
  }
  const upstream = new URL(
    `/outreach/campaigns/${encodeURIComponent(context.params.id)}/start`,
    `${apiUrl.replace(/\/$/, "")}/`,
  );
  const response = await fetch(upstream.toString(), { method: "POST", cache: "no-store" });
  return new Response(response.body, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
