import type { ReactNode } from 'react'

export type StatusBadgeTone =
  | 'teal'
  | 'neutral'
  | 'success'
  | 'warning'
  | 'error'
  | 'experimental'
  | 'ai'
  | 'synthetic'

interface StatusBadgeProps {
  tone?: StatusBadgeTone
  children: ReactNode
  className?: string
}

export function StatusBadge({
  tone = 'neutral',
  children,
  className = '',
}: StatusBadgeProps) {
  return (
    <span className={`terra-badge terra-badge--${tone} ${className}`.trim()}>
      {children}
    </span>
  )
}
