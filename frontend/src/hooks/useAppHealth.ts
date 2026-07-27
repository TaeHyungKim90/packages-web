import { useEffect, useState } from "react";
import { checkHealth } from "../api/client";

export function useAppHealth() {
  const [health, setHealth] = useState<"ok" | "error" | "loading">("loading");

  useEffect(() => {
    checkHealth()
      .then(() => setHealth("ok"))
      .catch(() => setHealth("error"));
  }, []);

  return health;
}
