import { useState } from "react";
import {
    Check,
    KeyRound,
    Lock,
    Mail,
    X,
} from "lucide-react";
import { toast } from "sonner";
import {
    changePasswordRequest,
    type UserPublic,
    updateHandleRequest,
} from "@/api/auth";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/useAuth";
import { getAvatarStyle } from "@/lib/avatarColor";
import { Card, CardContent } from "@/components/ui/card";
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
                        {/* Email row */}
                        <div className="flex items-center gap-4 border-b p-4">
                            <Mail className="size-5 text-muted-foreground" />
                            <div className="flex-1">
                                <p className="text-sm font-medium">Email</p>
                                <p className="truncate text-sm text-muted-foreground">{user.email}</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-4 border-b p-4">
                            <Lock className="size-5 text-muted-foreground" />
                            <div className="flex-1">
                                <p className="text-sm font-medium">Address</p>
                                <p className="truncate text-sm text-muted-foreground" title={user.eth_address}>{shortAddress(user.eth_address)}</p>
                                <p className="mt-1 text-xs text-muted-foreground">Do not send funds to this address. For API use only.</p>
                            </div>
                        </div>
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
    const avatarStyle = getAvatarStyle(user.eth_address || user.email);
    const displayName = user.handle || user.user_id;
    const avatarLabelSource = user.handle || user.email || user.user_id;
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
            setError("Username must be 1-15 chars using letters, numbers, or underscores.");
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
                    message = "Username must be 1-15 chars using letters, numbers, or underscores.";
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
                <div
                    className="flex size-9 items-center justify-center rounded-full text-xs font-semibold text-white"
                    style={avatarStyle}
                    aria-hidden
                >
                    {avatarLabelSource.slice(0, 1).toUpperCase()}
                </div>
                <div className="flex-1 flex items-center justify-between gap-4">
                    <div>
                        <p className="text-sm font-medium">Username</p>
                        {!editing && (
                            <p className="truncate text-sm text-muted-foreground">{displayName}</p>
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
                        <Button size="sm" variant="outline" onClick={startEdit}>Edit</Button>
                    )}
                </div>
            </div>
            {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
        </div>
    );
}


function shortAddress(address: string): string {
    if (!address) return "";
    if (address.length <= 22) return address;
    return `${address.slice(0, 12)}...${address.slice(-8)}`;
}

function maskWithLastVisible(value: string): string {
    if (!value) return "";
    if (value.length === 1) return value;
    return `${"•".repeat(value.length - 1)}${value[value.length - 1]}`;
}

function updateFromMaskedInput(previous: string, nextDisplay: string): string {
    if (!nextDisplay) return "";

    if (nextDisplay.length < previous.length) {
        return previous.slice(0, nextDisplay.length);
    }

    if (nextDisplay.length === previous.length + 1) {
        return `${previous}${nextDisplay[nextDisplay.length - 1]}`;
    }

    if (nextDisplay.length === previous.length) {
        return previous;
    }

    return previous;
}

function ChangePasswordRow() {
    const [showForm, setShowForm] = useState(false);
    const [current, setCurrent] = useState("");
    const [next, setNext] = useState("");
    const [confirm, setConfirm] = useState("");
    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSave = async () => {
        setError("");
        setSuccess("");
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
            setSuccess("Password changed successfully.");
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
        setSuccess("");
    };

    if (!showForm) {
        return (
            <div className="flex items-center gap-4 p-4">
                <KeyRound className="size-5 text-muted-foreground" />
                <div className="flex-1 flex items-center justify-between">
                    <div>
                        <p className="text-sm font-medium">Password</p>
                        <p className="text-xs text-muted-foreground">Change your account password</p>
                    </div>
                    <Button size="sm" variant="outline" onClick={() => setShowForm(true)}>Change</Button>
                </div>
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-2 p-4 border-t">
            <div className="flex items-center gap-4 mb-2">
                <KeyRound className="size-5 text-muted-foreground" />
                <span className="text-sm font-medium">Change Password</span>
            </div>
            <Input
                type="text"
                placeholder="Current password"
                value={maskWithLastVisible(current)}
                onChange={(e) => setCurrent((prev) => updateFromMaskedInput(prev, e.target.value))}
                name="current-password-change"
                autoComplete="off"
                data-lpignore="true"
                data-1p-ignore="true"
                className="mb-1"
                autoFocus
            />
            <Input
                type="text"
                placeholder="New password"
                value={maskWithLastVisible(next)}
                onChange={(e) => setNext((prev) => updateFromMaskedInput(prev, e.target.value))}
                name="new-password-change"
                autoComplete="off"
                data-lpignore="true"
                data-1p-ignore="true"
                className="mb-1"
            />
            <Input
                type="text"
                placeholder="Confirm new password"
                value={maskWithLastVisible(confirm)}
                onChange={(e) => setConfirm((prev) => updateFromMaskedInput(prev, e.target.value))}
                name="confirm-password-change"
                autoComplete="off"
                data-lpignore="true"
                data-1p-ignore="true"
                className="mb-2"
            />
            {error && <p className="text-xs text-red-500 mb-1">{error}</p>}
            {success && <p className="text-xs text-green-600 mb-1">{success}</p>}
            <div className="flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={handleCancel} disabled={loading}>Cancel</Button>
                <Button size="sm" onClick={handleSave} disabled={loading}>Save</Button>
            </div>
        </div>
    );
}


