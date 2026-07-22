import { useEffect, useState } from "react";
import { checkHealth } from "./api/client";

export default function App() {
  const [health, setHealth] = useState<string>("checking…");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    checkHealth()
      .then((data) => setHealth(data.status))
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "2rem" }}>
      <h1>packages-web</h1>
      <p>Nexus Proxy → Hosted 패키지 이관 도구</p>
      <p>
        Backend:{" "}
        {error ? (
          <span style={{ color: "crimson" }}>{error}</span>
        ) : (
          <span style={{ color: "green" }}>{health}</span>
        )}
      </p>
    </div>
  );
}
