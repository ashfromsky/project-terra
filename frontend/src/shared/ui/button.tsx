import type { ButtonHTMLAttributes, ReactNode } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'disabled' | 'utility'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  children: ReactNode
}

export function Button({
  variant = 'primary',
  className = '',
  disabled,
  type = 'button',
  children,
  ...rest
}: ButtonProps) {
  const effectiveVariant = disabled ? 'disabled' : variant
  const classes = `terra-btn terra-btn--${effectiveVariant} ${className}`.trim()

  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || variant === 'disabled'}
      {...rest}
    >
      {children}
    </button>
  )
}
