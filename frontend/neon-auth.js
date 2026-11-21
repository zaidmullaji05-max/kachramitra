/*
 * Neon Managed Better Auth client for Kachra Mitra's plain-JS frontend.
 *
 * Neon Auth exposes the signed JWT on the session as session.access_token.
 * Do not call client.getJWTToken() here: this adapter build routes that call
 * to a non-existent /get-jwt-token endpoint in the deployed project.
 */
try {
  const { createAuthClient } = await import("https://esm.sh/@neondatabase/auth");
  const authUrl = (window.WASTE_NEON_AUTH_URL || "").trim().replace(/\/+$/, "");
  if (!authUrl) throw new Error("Neon Auth URL is not configured");

  const client = createAuthClient(authUrl);

  function unwrap(result) {
    if (result?.error) {
      const error = result.error;
      throw new Error(error.message || error.statusText || "Neon Auth request failed");
    }
    return result?.data ?? result;
  }

  async function session() {
    return unwrap(await client.getSession());
  }

  function tokenFrom(payload) {
    // Neon Managed Auth returns the JWT as session.access_token.
    // Accept the common wrapper shapes returned by SDK versions.
    return payload?.session?.access_token
      || payload?.data?.session?.access_token
      || payload?.access_token
      || payload?.session?.accessToken
      || payload?.data?.session?.accessToken
      || null;
  }

  async function currentAuthState(operationResult) {
    const currentSession = await session();
    const token = tokenFrom(currentSession) || tokenFrom(operationResult);
    if (!token) {
      throw new Error(
        "Neon Auth signed in, but its session did not include an access_token. " +
        "Please check the Neon Auth SDK/session response before retrying."
      );
    }
    return { session: currentSession, token };
  }

  window.KMNeonAuth = {
    async signUp({ email, password, name }) {
      const result = unwrap(await client.signUp.email({ email, password, name }));
      return { result, ...(await currentAuthState(result)) };
    },
    async signIn({ email, password }) {
      const result = unwrap(await client.signIn.email({ email, password }));
      return { result, ...(await currentAuthState(result)) };
    },
    async getSession() {
      return currentAuthState(null);
    },
    async signOut() {
      await client.signOut();
    },
    async signInGoogle(callbackURL = window.location.origin) {
      return client.signIn.social({ provider: "google", callbackURL });
    }
  };

  window.dispatchEvent(new Event("kachra-neon-auth-ready"));
} catch (error) {
  console.error("Neon Auth SDK initialization failed:", error);
  window.dispatchEvent(new CustomEvent("kachra-neon-auth-error", { detail: error.message }));
}
