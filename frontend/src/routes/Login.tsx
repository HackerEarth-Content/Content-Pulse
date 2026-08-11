import { useEffect, useState } from "react";
import { BrandLockup } from "../components/Shell";
import { Banner } from "../components/ui";
import { useTheme } from "../hooks/useTheme";

export function Login() {
  const [theme] = useTheme();
  const [denied, setDenied] = useState(false);

  // The backend bounces a rejected Google account back here with a flag rather
  // than dumping JSON in the address bar.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("authError") === "not_allowed") {
      setDenied(true);
      params.delete("authError");
      const rest = params.toString();
      window.history.replaceState(null, "", window.location.pathname + (rest ? `?${rest}` : ""));
    }
  }, []);

  return (
    <div className="login-shell">
      <div className="login-card">
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 20 }}>
          <BrandLockup theme={theme} large />
        </div>
        <h1 className="login-title">Sign in</h1>
        <p className="login-sub">Plans, updates and analytics for the content team.</p>

        {denied ? (
          <Banner tone="error">
            That account isn't on the access list. Ask an admin to add your address.
          </Banner>
        ) : null}

        <a className="btn btn-primary" href="/api/auth/google/login" style={{ textDecoration: "none" }}>
          Continue with Google
        </a>
      </div>
    </div>
  );
}
