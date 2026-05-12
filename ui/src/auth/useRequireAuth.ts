import { useCallback } from "react";
import { useAuth } from "./useAuth";

/**
 * Wraps an action so it only fires when the user is signed in. If they're
 * signed out, opens the login dialog instead.
 *
 *   const requireAuth = useRequireAuth();
 *   <Button onClick={requireAuth(() => placeOrder.mutate(...))}>Buy</Button>
 */
export function useRequireAuth() {
  const { user, openLogin } = useAuth();
  return useCallback(
    <Args extends unknown[], R>(fn: (...args: Args) => R) =>
      (...args: Args): R | undefined => {
        if (!user) {
          openLogin();
          return undefined;
        }
        return fn(...args);
      },
    [user, openLogin],
  );
}
