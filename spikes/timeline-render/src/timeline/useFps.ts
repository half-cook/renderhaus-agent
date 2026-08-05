import { useCallback, useRef } from 'react';

/**
 * Returns a `report()` function — call it once per drawn frame from any
 * renderer's own render loop. Emits a rolling FPS reading via onFps twice a second.
 */
export function useFpsReporter(onFps: (fps: number) => void) {
  const frames = useRef(0);
  const lastReport = useRef(performance.now());

  return useCallback(() => {
    frames.current++;
    const now = performance.now();
    const elapsed = now - lastReport.current;
    if (elapsed >= 500) {
      onFps(Math.round((frames.current * 1000) / elapsed));
      frames.current = 0;
      lastReport.current = now;
    }
  }, [onFps]);
}
