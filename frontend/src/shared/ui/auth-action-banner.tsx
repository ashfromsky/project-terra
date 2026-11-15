import { buildGitHubLoginUrl, useDevSessionLoginMutation } from '../api/auth'
import { ApiError } from '../api/client'
import { useSystemInfoQuery } from '../api/system'
import { Button } from './button'

interface AuthActionBannerProps {
  returnTo: string
  title?: string
  description: string
}

export function AuthActionBanner({ returnTo, title, description }: AuthActionBannerProps) {
  const systemInfoQuery = useSystemInfoQuery()
  const devLoginMutation = useDevSessionLoginMutation()

  const oauthConfigured = systemInfoQuery.data?.githubOauthConfigured ?? false
  const devAuthEnabled = systemInfoQuery.data?.devAuthEnabled ?? false

  return (
    <div className="sci-banner sci-banner--warning">
      {title ? <strong>{title}</strong> : null}
      <p>{description}</p>
      <div className="sci-btn-row">
        {devAuthEnabled ? (
          <Button
            type="button"
            variant="primary"
            disabled={devLoginMutation.isPending}
            onClick={() => devLoginMutation.mutate()}
          >
            {devLoginMutation.isPending ? 'Starting dev session…' : 'Start Dev Session'}
          </Button>
        ) : null}
        {oauthConfigured ? (
          <a href={buildGitHubLoginUrl(returnTo)} className="terra-link-reset">
            <Button variant={devAuthEnabled ? 'secondary' : 'primary'}>Sign in with GitHub</Button>
          </a>
        ) : !devAuthEnabled ? (
          <span className="sci-dim-card__note">
            Authentication provider is not configured on Core API.
          </span>
        ) : null}
      </div>
      {devLoginMutation.isError ? (
        <p className="sci-dim-card__note" role="alert">
          {devLoginMutation.error instanceof ApiError
            ? devLoginMutation.error.message
            : String(devLoginMutation.error)}
        </p>
      ) : null}
    </div>
  )
}
