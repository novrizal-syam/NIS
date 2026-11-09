import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { syncAll } from './sync';

/** Keeps the offline queue moving: on reconnect, on a service-worker background sync, every
 * minute while open. Returns whether the browser is online. */
export function useDorSync(): boolean {
  const qc = useQueryClient();
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const flush = () => {
      void syncAll().then((n) => {
        if (n > 0) void qc.invalidateQueries({ queryKey: ['dors'] });
        window.dispatchEvent(new Event('dor-drafts-changed'));
      });
    };
    const up = () => {
      setOnline(true);
      flush();
    };
    const down = () => setOnline(false);
    const onMessage = (e: MessageEvent) => {
      if ((e.data as { type?: string } | null)?.type === 'dor-sync') flush();
    };
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    navigator.serviceWorker?.addEventListener('message', onMessage);
    const timer = window.setInterval(() => navigator.onLine && flush(), 60_000);
    if (navigator.onLine) flush();
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
      navigator.serviceWorker?.removeEventListener('message', onMessage);
      window.clearInterval(timer);
    };
  }, [qc]);
  return online;
}
