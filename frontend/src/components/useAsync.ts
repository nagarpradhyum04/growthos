import { useCallback, useEffect, useState } from "react";
import { describeError } from "../api";

/** Load data on mount (and on reload()); exposes loading + error state. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await loader());
      setError(null);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setError };
}

/** Wrap a user action: tracks busy state and turns failures into a readable message. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run<T>(label: string, fn: () => Promise<T>, success?: string): Promise<T | undefined> {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      const result = await fn();
      if (success) setNotice(success);
      return result;
    } catch (err) {
      setError(describeError(err));
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  return { busy, error, notice, run, setError, setNotice };
}
