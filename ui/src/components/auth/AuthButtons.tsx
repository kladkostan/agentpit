import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/auth/useAuth";

export function AuthButtons() {
  const { user, isLoading, openAuth } = useAuth();

  if (isLoading) {
    return <Skeleton className="h-9 w-24" />;
  }

  if (user) {
    return null;
  }
  // One button, because there is one door. "Log in" beside "Sign up" offered a
  // choice the product stopped being able to honour at the cutover: both
  // opened the same dialog, which asks for an address and mails a code that
  // signs you in or creates the account, whichever applies. Asking first which
  // one you meant would also mean asking the server whether the address is
  // known, and `POST /auth/code` answers 202 either way on purpose — so that a
  // stranger cannot use it to find out who has an account here.
  return (
    <Button size="sm" onClick={openAuth}>
      Sign in
    </Button>
  );
}
