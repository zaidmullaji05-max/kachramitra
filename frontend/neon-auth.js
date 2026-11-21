/*
 * Neon Managed Better Auth client for Kachra Mitra's existing plain-JS frontend.
 * The SDK is loaded as an ESM dependency; the app design and HTML forms stay unchanged.
 */
try {
  const { createAuthClient } = await import("https://esm.sh/@neondatabase/auth");
  const authUrl = (window.WASTE_NEON_AUTH_URL || "").trim();
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

  async function token() {
    const value = await client.getJWTToken();
    return value || null;
  }

  window.KMNeonAuth = {
    async signUp({ email, password, name }) {
      const result = unwrap(await client.signUp.email({ email, password, name }));
      return { result, session: await session(), token: await token() };
    },
    async signIn({ email, password }) {
      const result = unwrap(await client.signIn.email({ email, password }));
      return { result, session: await session(), token: await token() };
    },
    async getSession() {
      return { session: await session(), token: await token() };
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
