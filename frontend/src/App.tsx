import { Route, Routes } from "react-router-dom";
import {
  RedirectIfAuthed,
  RequireAuth,
  RootRedirect,
} from "./components/AuthGate";
import Layout from "./components/Layout";
import { useAppHealth } from "./hooks/useAppHealth";
import { useAuth } from "./hooks/useAuth";
import LoginPage from "./pages/LoginPage";
import PackageSearchPage from "./pages/PackageSearchPage";

export default function App() {
  const health = useAppHealth();
  const auth = useAuth();

  return (
    <Layout health={health} auth={auth}>
      <Routes>
        <Route path="/" element={<RootRedirect auth={auth} />} />

        <Route element={<RedirectIfAuthed auth={auth} />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>

        <Route element={<RequireAuth auth={auth} />}>
          <Route path="/search" element={<PackageSearchPage />} />
        </Route>
      </Routes>
    </Layout>
  );
}
