import { createContext } from "react";
import type { UserPublic } from "@/api/auth";

export type AuthValue = {
  user: UserPublic | null;
  setUser: (user: UserPublic | null) => void;
  accessToken: string | null;
  isLoading: boolean;
  /** Open the sign-in dialog. There is one, because signing in and signing up
   *  stopped being different actions at the cutover: a mailed code signs you
   *  in, and creates the account first if there isn't one.
   *
   *  Deliberately NOT two entry points that check first whether the address is
   *  known. `POST /auth/code` answers 202 either way precisely so a stranger
   *  cannot use it to discover who has an account here — and since the cutover
   *  retired `/register`'s 409, it is the only endpoint left that could leak
   *  that. Branching the UI on a lookup would hand back what the status code
   *  withholds. The branch happens on the server, after the code proves the
   *  caller owns the address. */
  openAuth: () => void;
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
