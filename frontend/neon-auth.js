/*
 * Neon Managed Better Auth adapter for Kachra Mitra.
 *
 * Managed Auth returns the application JWT in the `set-auth-jwt` response
 * header from GET /get-session. The HttpOnly session cookie is sent by the
 * browser; JavaScript must never read or copy the cookie itself.
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

  async function readSessionAndJwt() {
    // GET /get-session both returns session details and issues the JWT header.
    // credentials: include sends the HttpOnly Neon session cookie.
    const response = await fetch(`${authUrl}/get-session`, {
      method: "GET",
      credentials: "include",
      headers: { "Accept": "application/json" },
      cache: "no-store"
    });

    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const message = body?.message || body?.error || `Neon session request failed (HTTP ${response.status})`;
      throw new Error(message);
    }

    const token = response.headers.get("set-auth-jwt")
      || response.headers.get("Set-Auth-Jwt");
    if (!token) {
      throw new Error(
        "Neon Auth returned the session but did not expose the Set-Auth-Jwt response header. " +
        "Check that the Auth service exposes this header to the Vercel origin."
      );
    }
    return { session: body, token };
  }

  window.KMNeonAuth = {
    async signUp({ email, password, name }) {
      const result = unwrap(await client.signUp.email({ email, password, name }));
      return { result, ...(await readSessionAndJwt()) };
    },
    async signIn({ email, password }) {
      const result = unwrap(await client.signIn.email({ email, password }));
      return { result, ...(await readSessionAndJwt()) };
    },
    async getSession() {
      return readSessionAndJwt();
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
