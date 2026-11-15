export const onRequest: PagesFunction = async (context) => {
  const url = new URL(context.request.url)
  return Response.redirect(`${url.origin}/api/v1/auth/github/login?redirect=true`, 302)
}
