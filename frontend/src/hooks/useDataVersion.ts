import { useSyncExternalStore } from "react";

/** A counter every `useApi` call watches, so finishing a sync can refresh the
 * whole screen without remounting it.
 *
 * The alternative — keying the router on a nonce — refetches by throwing the
 * components away, which also throws away filters, the open tab and scroll
 * position. This changes the data under the same components.
 */
let version = 0;
const listeners = new Set<() => void>();

export function bumpDataVersion(): void {
  version += 1;
  listeners.forEach((notify) => notify());
}

export function useDataVersion(): number {
  return useSyncExternalStore(
    (notify) => {
      listeners.add(notify);
      return () => listeners.delete(notify);
    },
    () => version,
    () => version
  );
}
