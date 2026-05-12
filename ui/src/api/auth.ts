import { apiFetch } from "./client";

export type UserPublic = {
  user_id: string;
  email: string;
  handle: string | null;
  eth_address: string;
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

export function meRequest(): Promise<UserPublic> {
  return apiFetch<UserPublic>("/me");
}
