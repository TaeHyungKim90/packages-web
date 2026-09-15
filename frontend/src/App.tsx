import { Route, Routes } from "react-router";
import {
  RedirectIfAuthed,
  RequireAuth,
  RequireOrgsAccess,
  RequireRequestAccess,
  RootRedirect,
} from "./components/AuthGate";
import Layout from "./components/Layout";
import { useAppHealth } from "./hooks/useAppHealth";
import { useAuth } from "./hooks/useAuth";
import LoginPage from "./pages/LoginPage";
import GhesOrgsPage from "./pages/GhesOrgsPage";
import GhesMembersPage from "./pages/GhesMembersPage";
import ProjectPackagesPage from "./pages/ProjectPackagesPage";
import PackageRequestPage from "./pages/PackageRequestPage";
import PackageSearchPage from "./pages/PackageSearchPage";
import ProxyHealthPage from "./pages/ProxyHealthPage";

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
          <Route path="/vuln/pypi" element={<ProxyHealthPage packageType="pypi" />} />
          <Route path="/vuln/npm" element={<ProxyHealthPage packageType="npm" />} />
          <Route path="/vuln/nuget" element={<ProxyHealthPage packageType="nuget" />} />
        </Route>
        <Route element={<RequireRequestAccess auth={auth} />}>
          <Route path="/request/pypi" element={<PackageRequestPage packageType="pypi" />} />
          <Route path="/request/npm" element={<PackageRequestPage packageType="npm" />} />
          <Route path="/request/nuget" element={<PackageRequestPage packageType="nuget" />} />
        </Route>
        <Route element={<RequireOrgsAccess auth={auth} />}>
          <Route path="/orgs" element={<GhesOrgsPage />} />
          <Route path="/ghes-members" element={<GhesMembersPage />} />
          <Route path="/project-packages" element={<ProjectPackagesPage />} />
        </Route>
      </Routes>
    </Layout>
  );
}
