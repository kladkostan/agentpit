import { createContext } from "react";
import type { UserPublic } from "@/api/auth";

export type DialogMode = "login" | "signup";

export type AuthValue = {
  user: UserPublic | null;
  setUser: (user: UserPublic | null) => void;
  accessToken: string | null;
  isLoading: boolean;
  openLogin: () => void;
  openSignup: () => void;
  closeDialog: () => void;
  dialogOpen: boolean;
  dialogMode: DialogMode;
  setDialogMode: (mode: DialogMode) => void;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  /** Mail a six-digit code to this address. Resolves whether or not the
   *  address has an account — see `sendCodeRequest`. */
  sendCode: (email: string) => Promise<void>;
  signInWithCode: (email: string, code: string) => Promise<void>;
  signInWithGoogle: (credential: string) => Promise<void>;
  logout: () => void;
};

export const AuthContext = createContext<AuthValue | null>(null);
