import type { SVGProps } from 'react'

export interface IconProps extends SVGProps<SVGSVGElement> {
  size?: number
}

function SvgIcon({ paths, size = 16, ...rest }: IconProps & { paths: readonly string[] }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" {...rest}>
      {paths.map((d) => <path key={d} d={d} />)}
    </svg>
  )
}

export function AlertCircle(p: IconProps) {
  return <SvgIcon {...p} paths={['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'M12 8v4', 'M12 16h.01']} />
}

export function AlertTriangle(p: IconProps) {
  return <SvgIcon {...p} paths={['m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z', 'M12 9v4', 'M12 17h.01']} />
}

export function Calendar(p: IconProps) {
  return <SvgIcon {...p} paths={['M8 2v4', 'M16 2v4', 'M3 10h18', 'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z']} />
}

export function Check(p: IconProps) {
  return <SvgIcon {...p} paths={['M20 6 9 17l-5-5']} />
}

export function ChevronDown(p: IconProps) {
  return <SvgIcon {...p} paths={['m6 9 6 6 6-6']} />
}

export function ChevronLeft(p: IconProps) {
  return <SvgIcon {...p} paths={['m15 18-6-6 6-6']} />
}

export function ChevronRight(p: IconProps) {
  return <SvgIcon {...p} paths={['m9 18 6-6-6-6']} />
}

export function ChevronUp(p: IconProps) {
  return <SvgIcon {...p} paths={['m18 15-6-6-6 6']} />
}

export function Columns2(p: IconProps) {
  return <SvgIcon {...p} paths={['M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z', 'M12 3v18']} />
}

export function Compass(p: IconProps) {
  return <SvgIcon {...p} paths={['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'm16.24 7.76-2.12 6.36-6.36 2.12 2.12-6.36 6.36-2.12Z']} />
}

export function Crosshair(p: IconProps) {
  return <SvgIcon {...p} paths={['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'M22 12h-4', 'M6 12H2', 'M12 6V2', 'M12 22v-4']} />
}

export function Download(p: IconProps) {
  return <SvgIcon {...p} paths={['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'm7 10 5 5 5-5', 'M12 15V3']} />
}

export function Eye(p: IconProps) {
  return <SvgIcon {...p} paths={['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z', 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z']} />
}

export function EyeOff(p: IconProps) {
  return <SvgIcon {...p} paths={['M9.88 9.88a3 3 0 1 0 4.24 4.24', 'M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68', 'M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61', 'M2 2l20 20']} />
}

export function Globe(p: IconProps) {
  return <SvgIcon {...p} paths={['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'M2 12h20', 'M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10Z']} />
}

export function Info(p: IconProps) {
  return <SvgIcon {...p} paths={['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'M12 16v-4', 'M12 8h.01']} />
}

export function Layers(p: IconProps) {
  return <SvgIcon {...p} paths={['m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z', 'm2 12 10 4.5L22 12', 'm2 17 10 4.5L22 17']} />
}

export function Link2(p: IconProps) {
  return <SvgIcon {...p} paths={['M9 17H7A5 5 0 0 1 7 7h2', 'M15 7h2a5 5 0 1 1 0 10h-2', 'M8 12h8']} />
}

export function Link2Off(p: IconProps) {
  return <SvgIcon {...p} paths={['M9 17H7A5 5 0 0 1 7 7h2', 'M15 7h2a5 5 0 0 1 4 8', 'M8 12h4', 'M2 2l20 20']} />
}

export function MapIcon(p: IconProps) {
  return <SvgIcon {...p} paths={['M3 6v14l6-3 6 3 6-3V3l-6 3-6-3-6 3Z', 'M9 3v14', 'M15 6v14']} />
}

export function MapPin(p: IconProps) {
  return <SvgIcon {...p} paths={['M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z', 'M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z']} />
}

export function Maximize2(p: IconProps) {
  return <SvgIcon {...p} paths={['M15 3h6v6', 'M9 21H3v-6', 'M21 3l-7 7', 'M3 21l7-7']} />
}

export function Minimize2(p: IconProps) {
  return <SvgIcon {...p} paths={['M4 14h6v6', 'M20 10h-6V4', 'M14 10l7-7', 'M3 21l7-7']} />
}

export function Minus(p: IconProps) {
  return <SvgIcon {...p} paths={['M5 12h14']} />
}

export function MousePointerClick(p: IconProps) {
  return <SvgIcon {...p} paths={['m9 9 5 12 1.8-5.2L21 14 9 9Z', 'M7.2 2.2 8 5.1', 'm5.1 8-2.9-.8', 'm14 4.1-1.9 2.2', 'm6.3 12.1-2.2 1.9']} />
}

export function PanelRight(p: IconProps) {
  return <SvgIcon {...p} paths={['M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z', 'M15 3v18']} />
}

export function Pause(p: IconProps) {
  return <SvgIcon {...p} paths={['M6 4h4v16H6z', 'M14 4h4v16h-4z']} />
}

export function Pentagon(p: IconProps) {
  return <SvgIcon {...p} paths={['M3.5 8.7c-.7.5-.9 1.4-.7 2.2l2.8 8.7c.3.8 1 1.4 1.9 1.4h9.1c.9 0 1.6-.6 1.9-1.4l2.8-8.7c.3-.8 0-1.7-.7-2.2l-7.4-5.3a2 2 0 0 0-2.4 0Z']} />
}

export function Play(p: IconProps) {
  return <SvgIcon {...p} paths={['m6 3 14 9-14 9V3Z']} />
}

export function Plus(p: IconProps) {
  return <SvgIcon {...p} paths={['M12 5v14', 'M5 12h14']} />
}

export function RotateCcw(p: IconProps) {
  return <SvgIcon {...p} paths={['M3 12a9 9 0 1 0 3-6.7L3 8', 'M3 3v5h5']} />
}

export function Search(p: IconProps) {
  return <SvgIcon {...p} paths={['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z', 'm21 21-4.3-4.3']} />
}

export function SlidersHorizontal(p: IconProps) {
  return <SvgIcon {...p} paths={['M21 4h-7', 'M10 4H3', 'M21 12h-9', 'M8 12H3', 'M21 20h-5', 'M12 20H3', 'M14 2v4', 'M8 10v4', 'M16 18v4']} />
}

export function Square(p: IconProps) {
  return <SvgIcon {...p} paths={['M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z']} />
}

export function Trash2(p: IconProps) {
  return <SvgIcon {...p} paths={['M3 6h18', 'M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6', 'M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2', 'M10 11v6', 'M14 11v6']} />
}

export function X(p: IconProps) {
  return <SvgIcon {...p} paths={['M18 6 6 18', 'M6 6l12 12']} />
}

export function ExternalLink(p: IconProps) {
  return (
    <SvgIcon
      {...p}
      paths={[
        'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6',
        'M15 3h6v6',
        'M10 14 21 3',
      ]}
    />
  )
}

export function Github(p: IconProps) {
  return (
    <svg
      width={p.size ?? 16}
      height={p.size ?? 16}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...p}
    >
      <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
      <path d="M9 18c-4.51 2-5-2-7-2" />
    </svg>
  )
}

export function ObservatoryFrameIcon({ size = 15, ...rest }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" {...rest}>
      <path d="M4 9V5a1 1 0 0 1 1-1h4" />
      <path d="M15 4h4a1 1 0 0 1 1 1v4" />
      <path d="M20 15v4a1 1 0 0 1-1 1h-4" />
      <path d="M9 20H5a1 1 0 0 1-1-1v-4" />
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 7v1.5M12 15.5V17M7 12h1.5M15.5 12H17" />
    </svg>
  )
}
