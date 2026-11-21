/*
 * Neon Managed Auth adapter for Kachra Mitra.
 * The SDK manages the HttpOnly session cookie. Retrieve the short-lived JWT
 * using the Managed Auth token endpoint as a fallback for SDK builds whose
 * session response does not expose access_token to this plain-JS wrapper.
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
    return payload?.token
      || payload?.data?.token
      || payload?.session?.access_token
      || payload?.data?.session?.access_token
      || payload?.access_token
      || payload?.data?.access_token
      || null;
  }

  async function getToken(operationResult) {
    // First use the SDK helper when it returns a token.
    if (typeof client.getJWTToken === "function") {
      try {
        const sdkToken = await client.getJWTToken();
        if (typeof sdkToken === "string" && sdkToken.length > 20) return sdkToken;
        const nested = tokenFrom(sdkToken);
        if (nested) return nested;
      } catch (err) {
        console.warn("Neon SDK JWT helper failed; trying /token endpoint:", err);
      }
    }

    // Neon Managed Auth's token endpoint uses the existing HttpOnly session cookie.
    const response = await fetch(`${authUrl}/token`, {
      method: "GET",
      credentials: "include",
      headers: { "Accept": "application/json" },
      cache: "no-store"
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = body?.message || body?.error || `Token endpoint returned HTTP ${response.status}`;
      throw new Error(message);
    }
    const token = tokenFrom(body) || tokenFrom(operationResult);
    if (!token) {
      throw new Error("Neon Auth did not return a JWT. Check the browser's /token response and session cookie.");
    }
    return token;
  }

  async function currentAuthState(operationResult) {
    const currentSession = await session();
    const token = await getToken(operationResult);
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
