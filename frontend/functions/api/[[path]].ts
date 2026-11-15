interface Env {
  BACKEND_API_URL?: string
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const backendUrl = context.env.BACKEND_API_URL

  if (!backendUrl) {
    return new Response(
      JSON.stringify({
        detail: 'Core Backend API is not connected. Configure BACKEND_API_URL in Cloudflare Pages settings.',
        status: 'disconnected',
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

  const reqHeaders = new Headers(context.request.headers)
  reqHeaders.delete('host')
  reqHeaders.set('X-Forwarded-Host', url.host)
  reqHeaders.set('X-Forwarded-Proto', url.protocol.replace(':', ''))

  const forwardedRequest = new Request(targetUrl, {
    method: context.request.method,
    headers: reqHeaders,
    body: ['GET', 'HEAD'].includes(context.request.method) ? undefined : context.request.body,
    redirect: 'manual',
  })

  try {
    return await fetch(forwardedRequest)
  } catch (error) {
    return new Response(
      JSON.stringify({
        detail: `Failed to proxy request to backend: ${String(error)}`,
        status: 'error',
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
