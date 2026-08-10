import { apiFetch } from "./client";

export type UserPublic = {
  user_id: string;
  email: string;
  handle: string | null;
  eth_address: string;
  api_key: string;
  has_password: boolean;
  onboarded_at: number | null;
  created_at: number;
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: UserPublic;
};

export function loginRequest(
  email: string,
  password: string,
): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function registerRequest(
  email: string,
  password: string,
): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export type GoogleAuthResponse = AuthResponse & {
  /** True when this sign-in created the account. */
  created: boolean;
};

export function googleSignInRequest(
  credential: string,
): Promise<GoogleAuthResponse> {
  return apiFetch<GoogleAuthResponse>("/auth/google", {
    method: "POST",
    body: JSON.stringify({ credential }),
  });
}

export function meRequest(): Promise<UserPublic> {
  return apiFetch<UserPublic>("/me");
}

export function updateHandleRequest(handle: string): Promise<UserPublic> {
  return apiFetch<UserPublic>("/me", {
    method: "PATCH",
    body: JSON.stringify({ handle }),
  });
}

export function changePasswordRequest(
  currentPassword: string,
  newPassword: string,
): Promise<UserPublic> {
  return apiFetch<UserPublic>("/me/password", {
    method: "PATCH",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export function exportPrivateKeyRequest(
  factor: { password: string } | { googleCredential: string },
): Promise<{ private_key: string; eth_address: string }> {
  const body =
    "password" in factor
      ? { password: factor.password }
      : { google_credential: factor.googleCredential };
  return apiFetch<{ private_key: string; eth_address: string }>(
    "/me/private-key",
    { method: "POST", body: JSON.stringify(body) },
  );
}
