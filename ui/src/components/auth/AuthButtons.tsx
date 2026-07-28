import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/auth/useAuth";

export function AuthButtons() {
  const { user, isLoading, openLogin } = useAuth();

  if (isLoading) {
    return <Skeleton className="h-9 w-32" />;
  }

  if (user) {
    return null;
  }
  return (
    <div className="flex items-center gap-2">
      <Button variant="ghost" size="sm" onClick={openLogin}>
        Log in
      </Button>
    </div>
  );
}
