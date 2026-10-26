import { store } from "./store";

/** Remove one session. */
export function revokeSession(id: string): void {
  store.delete(id);
}
