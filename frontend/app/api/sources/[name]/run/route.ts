import { NextRequest } from "next/server";

export async function POST(
  _request: NextRequest,
  context: { params: { name: string } },
): Promise<Response> {
  const apiUrl = process.env.API_URL;
  if (!apiUrl) {
    return new Response("API_URL is not set", { status: 500 });
  }
  const upstream = new URL(
    `/sources/${encodeURIComponent(context.params.name)}/run`,
    `${apiUrl.replace(/\/$/, "")}/`,
  );
  const response = await fetch(upstream.toString(), { method: "POST", cache: "no-store" });
  return new Response(response.body, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
