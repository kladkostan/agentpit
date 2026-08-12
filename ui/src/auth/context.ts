import { createContext } from "react";
import type { UserPublic } from "@/api/auth";

export type AuthValue = {
  user: UserPublic | null;
  setUser: (user: UserPublic | null) => void;
  accessToken: string | null;
  isLoading: boolean;
  /** Both open the same dialog. Signing in and signing up are one action now
   *  — a mailed code creates the account if there isn't one — but the two
   *  names are kept because the callers still mean different things by them:
   *  a nav button, a landing-page call to action, a gate on a click. */
  openLogin: () => void;
  openSignup: () => void;
  closeDialog: () => void;
  dialogOpen: boolean;
  /** Mail a six-digit code to this address. Resolves whether or not the
   *  address has an account — see `sendCodeRequest`. */
  sendCode: (email: string) => Promise<void>;
  signInWithCode: (email: string, code: string) => Promise<void>;
  signInWithGoogle: (credential: string) => Promise<void>;
  /** Finish a provider redirect: exchange its code for a session. */
  signInWithCallbackCode: (code: string) => Promise<void>;
  logout: () => void;
};

export const AuthContext = createContext<AuthValue | null>(null);
