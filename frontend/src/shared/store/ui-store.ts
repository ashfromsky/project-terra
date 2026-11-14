import { create } from 'zustand'

/**
 * Shared client-side UI state.
 *
 * Intended for ephemeral interface state only (panel visibility, active
 * dialogs, ...). Server data belongs in TanStack Query, not here.
 */
interface UiState {
  /** Whether the side panel is visible. */
  panelOpen: boolean
  togglePanel: () => void
}

export const useUiStore = create<UiState>()((set) => ({
  panelOpen: true,
  togglePanel: () => set((state) => ({ panelOpen: !state.panelOpen })),
}))
