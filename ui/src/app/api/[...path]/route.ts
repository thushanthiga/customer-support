import { NextRequest, NextResponse } from "next/server";

export const maxDuration = 180;
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handleProxy(request, path);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handleProxy(request, path);
}

export async function PUT(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handleProxy(request, path);
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handleProxy(request, path);
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return handleProxy(request, path);
}

async function handleProxy(request: NextRequest, path: string[]) {
  const apiTarget = (process.env.SUPPORT_ASSISTANT_API_URL || "http://127.0.0.1:8000/api").replace(/\/$/, "");
  const search = request.nextUrl.search || "";
  const cleanSubPath = (path || []).filter(Boolean).join("/");
  const queryString = search ? (search.startsWith("?") ? search : `?${search}`) : "";
  const targetUrl = cleanSubPath ? `${apiTarget}/${cleanSubPath}/${queryString}` : `${apiTarget}/${queryString}`;

  const hopByHopHeaders = new Set([
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
  ]);

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!hopByHopHeaders.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  try {
    const isBodyAllowed = request.method !== "GET" && request.method !== "HEAD";
    const body = isBodyAllowed ? await request.text() : undefined;

    const res = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(150000),
    });

    const responseData = await res.arrayBuffer();
    return new NextResponse(responseData, {
      status: res.status,
      statusText: res.statusText,
      headers: res.headers,
    });
  } catch (err: any) {
    const isTimeout = err?.name === "TimeoutError" || err?.code === 23;
    const isUnreachable = err?.cause?.code === "ECONNREFUSED" || err?.message?.includes("fetch failed");
    const status = isTimeout ? 504 : isUnreachable ? 503 : 502;
    const message = isTimeout
      ? "The support server took too long to answer this request. Please narrow your question or retry."
      : isUnreachable
        ? "Cannot reach the support server. Ensure the backend service is running and try again."
        : `The support server could not complete this request: ${err?.message || "Unknown error"}`;
    console.error(`[Apptimate Proxy Error] Failed to proxy ${request.method} ${targetUrl} (${status}):`, err);
    return NextResponse.json({ error: message }, { status });
  }
}

