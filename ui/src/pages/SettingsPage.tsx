import { useState } from "react";
import { Check, Copy, Eye, EyeOff, Key, KeyRound, Lock, Mail, User, X } from "lucide-react";
import { toast } from "sonner";
import {
  changePasswordRequest,
  exportPrivateKeyRequest,
  type UserPublic,
  updateHandleRequest,
} from "@/api/auth";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/useAuth";
import { GoogleSignInButton } from "@/components/auth/GoogleSignInButton";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export function SettingsPage() {
  const { user, setUser } = useAuth();
  if (!user) return null;
  return (
    <section className="mx-auto max-w-5xl space-y-6">
      <div className="space-y-6">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <Card className="rounded-xl">
          <CardContent className="p-0">
            <UsernameRow user={user} onUpdated={setUser} />
            <div className="flex items-center gap-4 border-b p-4">
              <Mail className="size-5 text-muted-foreground" />
              <div className="flex-1">
                <p className="text-sm font-medium">Email</p>
                <p className="truncate text-sm text-muted-foreground">
                  {user.email}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4 border-b p-4">
              <Lock className="size-5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Address</p>
                <p className="break-all font-mono text-sm text-muted-foreground">
                  {user.eth_address}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Import it into MetaMask to fund this wallet.
                </p>
              </div>
              <ExportKeyButton />
            </div>
            <ApiKeyRow apiKey={user.api_key} />
            <ChangePasswordRow />
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

type UsernameRowProps = {
  user: UserPublic;
  onUpdated: (user: UserPublic) => void;
};

function UsernameRow({ user, onUpdated }: UsernameRowProps) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const displayName = user.handle || user.user_id;
  const [value, setValue] = useState(displayName);

  const startEdit = () => {
    setValue(displayName);
    setError("");
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setValue(displayName);
    setError("");
  };

  const save = async () => {
    const next = value.trim();
    if (!/^[a-zA-Z0-9_]{1,15}$/.test(next)) {
      setError(
        "Username must be 1-15 chars using letters, numbers, or underscores.",
      );
      return;
    }
    if (next === displayName) {
      setEditing(false);
      setError("");
      return;
    }

    setSaving(true);
    setError("");
    try {
      const updated = await updateHandleRequest(next);
      onUpdated(updated);
      setEditing(false);
      toast.success("Username updated.");
    } catch (err) {
      let message = "Failed to update username.";
      if (err instanceof ApiError) {
        if (err.status === 409) {
          message = "That username is already taken.";
        } else if (err.status === 400 || err.status === 422) {
          message =
            "Username must be 1-15 chars using letters, numbers, or underscores.";
        }
      }
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border-b p-4">
      <div className="flex items-center gap-4">
        <User className="size-5 text-muted-foreground" aria-hidden />
        <div className="flex flex-1 items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Username</p>
            {!editing && (
              <p className="truncate text-sm text-muted-foreground">
                {displayName}
              </p>
            )}
          </div>

          {editing ? (
            <div className="flex items-center gap-2">
              <Input
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void save();
                  }
                  if (e.key === "Escape") {
                    e.preventDefault();
                    cancelEdit();
                  }
                }}
                disabled={saving}
                autoFocus
                className="w-64 sm:w-72"
              />
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="size-9 rounded-full"
                onClick={cancelEdit}
                disabled={saving}
                aria-label="Cancel username edit"
              >
                <X className="size-4" />
              </Button>
              <Button
                type="button"
                size="icon"
                className="size-9 rounded-full"
                onClick={() => void save()}
                disabled={saving}
                aria-label="Save username"
              >
                <Check className="size-4" />
              </Button>
            </div>
          ) : (
            <Button size="sm" variant="outline" onClick={startEdit}>
              Edit
            </Button>
          )}
        </div>
      </div>
      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
    </div>
  );
}

function ApiKeyRow({ apiKey }: { apiKey: string }) {
  const [revealed, setRevealed] = useState(false);
  const masked = apiKey
    ? `${apiKey.slice(0, 6)}${"•".repeat(10)}${apiKey.slice(-4)}`
    : "—";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(apiKey);
      toast.success("API key copied to clipboard.");
    } catch {
      toast.error("Could not copy API key.");
    }
  };

  return (
    <div className="flex items-center gap-4 border-b p-4">
      <Key className="size-5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">Agentpit API Key</p>
        <p
          className="truncate font-mono text-sm text-muted-foreground"
          title={revealed ? apiKey : undefined}
        >
          {revealed ? apiKey : masked}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-9 rounded-full"
          onClick={() => setRevealed((r) => !r)}
          aria-label={revealed ? "Hide API key" : "Reveal API key"}
        >
          {revealed ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-9 rounded-full"
          onClick={() => void copy()}
          aria-label="Copy API key"
        >
          <Copy className="size-4" />
        </Button>
      </div>
    </div>
  );
}

type ExportedKey = { private_key: string; eth_address: string };

function ExportKeyButton() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ExportedKey | null>(null);

  const reset = () => {
    setPassword("");
    setError("");
    setLoading(false);
    setResult(null);
  };

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) reset();
  };

  const submit = async (factor: { password: string } | { googleCredential: string }) => {
    setError("");
    setLoading(true);
    try {
      const exported = await exportPrivateKeyRequest(factor);
      setResult(exported);
    } catch (err) {
      let message = "Failed to export private key.";
      if (err instanceof ApiError) {
        if (err.status === 401) {
          message = "Incorrect password.";
        } else if (err.status === 400) {
          message = "Too many attempts. Wait a moment and try again.";
        }
      }
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  const copy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.private_key);
      toast.success("Private key copied to clipboard.");
    } catch {
      toast.error("Could not copy private key.");
    }
  };

  if (!user) return null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          Export private key
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Export private key</DialogTitle>
          <DialogDescription>
            Anyone with this key controls the wallet and everything in it. We
            cannot undo an export or move the funds back.
          </DialogDescription>
        </DialogHeader>
        {result ? (
          <div className="flex flex-col gap-3">
            <p className="break-all rounded-md border bg-muted p-3 font-mono text-sm">
              {result.private_key}
            </p>
            <Button type="button" variant="outline" onClick={() => void copy()}>
              <Copy className="mr-2 size-4" />
              Copy private key
            </Button>
          </div>
        ) : user.has_password ? (
          <div className="flex flex-col gap-2">
            <Input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              autoFocus
              disabled={loading}
              onKeyDown={(e) => {
                if (e.key === "Enter" && password && !loading) {
                  e.preventDefault();
                  void submit({ password });
                }
              }}
            />
            {error && <p className="text-xs text-red-500">{error}</p>}
            <Button
              type="button"
              onClick={() => void submit({ password })}
              disabled={loading || !password}
            >
              Confirm
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <GoogleSignInButton
              onCredential={(credential) =>
                void submit({ googleCredential: credential })
              }
              onError={setError}
            />
            {error && <p className="text-xs text-red-500">{error}</p>}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ChangePasswordRow() {
  const [showForm, setShowForm] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSave = async () => {
    setError("");
    if (!current || !next || !confirm) {
      setError("All fields are required.");
      return;
    }
    if (next !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (current === next) {
      setError("New password must be different from current password.");
      return;
    }
    setLoading(true);
    try {
      await changePasswordRequest(current, next);
      toast.success("Password changed successfully.");
      setShowForm(false);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      let message = "Failed to change password.";
      if (err instanceof ApiError) {
        if (err.status === 401) {
          message = "Current password is incorrect.";
        } else if (err.status === 422) {
          message = "New password must be at least 8 characters.";
        } else if (err.status === 400) {
          message = "New password must be different from current password.";
        }
      }
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    setShowForm(false);
    setCurrent("");
    setNext("");
    setConfirm("");
    setError("");
  };

  if (!showForm) {
    return (
      <div className="flex items-center gap-4 p-4">
        <KeyRound className="size-5 text-muted-foreground" />
        <div className="flex flex-1 items-center justify-between">
          <div>
            <p className="text-sm font-medium">Password</p>
            <p className="text-xs text-muted-foreground">
              Change your account password
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={() => setShowForm(true)}>
            Change
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 border-t p-4">
      <div className="mb-2 flex items-center gap-4">
        <KeyRound className="size-5 text-muted-foreground" />
        <span className="text-sm font-medium">Change Password</span>
      </div>
      <Input
        type="password"
        placeholder="Current password"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
        autoComplete="current-password"
        className="mb-1"
        autoFocus
      />
      <Input
        type="password"
        placeholder="New password"
        value={next}
        onChange={(e) => setNext(e.target.value)}
        autoComplete="new-password"
        className="mb-1"
      />
      <Input
        type="password"
        placeholder="Confirm new password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        autoComplete="new-password"
        className="mb-2"
      />
      {error && <p className="mb-1 text-xs text-red-500">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button
          size="sm"
          variant="ghost"
          onClick={handleCancel}
          disabled={loading}
        >
          Cancel
        </Button>
        <Button size="sm" onClick={handleSave} disabled={loading}>
          Save
        </Button>
      </div>
    </div>
  );
}
