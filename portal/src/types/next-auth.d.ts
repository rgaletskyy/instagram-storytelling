import "next-auth";
import "next-auth/jwt";

type SessionError = "RefreshTokenMissing" | "RefreshFailed";

declare module "next-auth" {
  interface Session {
    error?: SessionError;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    idToken?: string;
    refreshToken?: string;
    error?: SessionError;
  }
}
