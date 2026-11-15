interface Env {
  BACKEND_API_URL?: string
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const backendUrl = context.env.BACKEND_API_URL

  if (!backendUrl) {
    return new Response(
      JSON.stringify({
        status: 'disconnected',
        detail: 'Core Backend API is not connected. Configure BACKEND_API_URL in Cloudflare Pages settings.',
      }),
      {
        status: 503,
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-store',
        },
      },
    )
  }

  const url = new URL(context.request.url)
  const normalizedBase = backendUrl.replace(/\/+$/, '')
  const targetUrl = `${normalizedBase}${url.pathname}${url.search}`

  const forwardedRequest = new Request(targetUrl, {
    method: context.request.method,
    headers: context.request.headers,
    redirect: 'follow',
  })

  try {
    return await fetch(forwardedRequest)
  } catch (error) {
    return new Response(
      JSON.stringify({
        status: 'error',
        detail: `Failed to proxy health check to backend: ${String(error)}`,
      }),
      {
        status: 502,
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-store',
        },
      },
    )
  }
}
