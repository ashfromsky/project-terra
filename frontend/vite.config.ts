import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Environment variables live in a single root .env (see .env.example at the
  // repository root) so the frontend and backend are configured from one place.
  envDir: '..',
})
