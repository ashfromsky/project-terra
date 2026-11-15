import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  ScienceResult,
  ScienceWorkerMessage,
  ScienceWorkerRequest,
} from './science-types'

export interface ScienceWorkerState {
  status: 'idle' | 'running' | 'success' | 'error'
  message: string | null
  progress: { completed: number; total: number } | null
  result: ScienceResult | null
  error: string | null
}

const INITIAL_STATE: ScienceWorkerState = {
  status: 'idle',
  message: null,
  progress: null,
  result: null,
  error: null,
}

export function useScienceWorker() {
  const workerRef = useRef<Worker | null>(null)
  const [state, setState] = useState<ScienceWorkerState>(INITIAL_STATE)

  const cancel = useCallback(() => {
    workerRef.current?.terminate()
    workerRef.current = null
    setState((prev) =>
      prev.status === 'running'
        ? { ...prev, status: 'idle', message: 'Calculation cancelled.' }
        : prev,
    )
  }, [])

  useEffect(() => () => workerRef.current?.terminate(), [])

  const run = useCallback((request: ScienceWorkerRequest) => {
    workerRef.current?.terminate()
    const worker = new Worker(new URL('../workers/science.worker.ts', import.meta.url), {
      type: 'module',
    })
    workerRef.current = worker
    setState({ status: 'running', message: 'Starting client-side calculation…', progress: null, result: null, error: null })
    worker.onmessage = (event: MessageEvent<ScienceWorkerMessage>) => {
      const message = event.data
      if (message.type === 'progress') {
        setState((prev) => ({
          ...prev,
          message: message.message ?? prev.message,
          progress:
            message.completed !== undefined && message.total !== undefined
              ? { completed: message.completed, total: message.total }
              : prev.progress,
        }))
        return
      }
      if (message.type === 'result' && message.result) {
        setState({
          status: 'success',
          message: 'Calculation completed in the browser.',
          progress: null,
          result: message.result,
          error: null,
        })
        worker.terminate()
        workerRef.current = null
        return
      }
      setState({
        status: 'error',
        message: null,
        progress: null,
        result: null,
        error: message.error ?? 'Client-side calculation failed.',
      })
      worker.terminate()
      workerRef.current = null
    }
    worker.onerror = (event) => {
      setState({
        status: 'error',
        message: null,
        progress: null,
        result: null,
        error: event.message || 'Science Web Worker failed.',
      })
      worker.terminate()
      workerRef.current = null
    }
    worker.postMessage(request)
  }, [])

  return { ...state, run, cancel }
}
