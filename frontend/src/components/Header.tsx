import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";

const ECOSYSTEMS = [
  { type: "pypi", label: "pypi" },
  { type: "npm", label: "npm" },
  { type: "nuget", label: "nuget" },
] as const;

type MenuId = "request" | "vuln" | "admin";

export default function Header({
  canRequest = false,
  canViewOrgs = false,
}: {
  canRequest?: boolean;
  canViewOrgs?: boolean;
}) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const requestActive = pathname.startsWith("/request");
  const vulnActive = pathname.startsWith("/vuln");
  const adminActive =
    pathname.startsWith("/orgs") ||
    pathname.startsWith("/project-packages") ||
    pathname.startsWith("/ghes-members");
  const [openMenu, setOpenMenu] = useState<MenuId | null>(null);

  useEffect(() => {
    setOpenMenu(null);
  }, [pathname]);

  return (
    <nav className="header-nav" aria-label="메인 메뉴">
      <ul className="header-nav__list">
        <li className="header-nav__item">
          <NavLink
            to="/search"
            className={({ isActive }) =>
              `header-nav__link${isActive ? " header-nav__link--active" : ""}`
            }
            end
          >
            패키지검색
          </NavLink>
        </li>
        {canRequest && (
        <Dropdown
          id="request"
          label="패키지신청"
          active={requestActive}
          open={openMenu === "request"}
          onHover={(open) => setOpenMenu(open ? "request" : null)}
          onParentClick={() => {
            navigate("/request/pypi");
            setOpenMenu(null);
          }}
        >
          {ECOSYSTEMS.map((item) => (
            <li key={item.type}>
              <NavLink
                to={`/request/${item.type}`}
                className={({ isActive }) =>
                  `header-nav__sublink${isActive ? " header-nav__sublink--active" : ""}`
                }
                onClick={() => setOpenMenu(null)}
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </Dropdown>
        )}
        <Dropdown
          id="vuln"
          label="패키지 보안 취약점"
          active={vulnActive}
          open={openMenu === "vuln"}
          onHover={(open) => setOpenMenu(open ? "vuln" : null)}
          onParentClick={() => {
            navigate("/vuln/pypi");
            setOpenMenu(null);
          }}
        >
          {ECOSYSTEMS.map((item) => (
            <li key={item.type}>
              <NavLink
                to={`/vuln/${item.type}`}
                className={({ isActive }) =>
                  `header-nav__sublink${isActive ? " header-nav__sublink--active" : ""}`
                }
                onClick={() => setOpenMenu(null)}
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </Dropdown>
        {canViewOrgs && (
          <Dropdown
            id="admin"
            label="관리"
            active={adminActive}
            open={openMenu === "admin"}
            onHover={(open) => setOpenMenu(open ? "admin" : null)}
            onParentClick={() => {
              navigate("/orgs");
              setOpenMenu(null);
            }}
          >
            <li>
              <NavLink
                to="/orgs"
                className={({ isActive }) =>
                  `header-nav__sublink${isActive ? " header-nav__sublink--active" : ""}`
                }
                onClick={() => setOpenMenu(null)}
              >
                GHES 조직
              </NavLink>
            </li>
            <li>
              <NavLink
                to="/ghes-members"
                className={({ isActive }) =>
                  `header-nav__sublink${isActive ? " header-nav__sublink--active" : ""}`
                }
                onClick={() => setOpenMenu(null)}
              >
                GHES 가입자
              </NavLink>
            </li>
            <li>
              <NavLink
                to="/project-packages"
                className={({ isActive }) =>
                  `header-nav__sublink${isActive ? " header-nav__sublink--active" : ""}`
                }
                onClick={() => setOpenMenu(null)}
              >
                과제별 패키지
              </NavLink>
            </li>
          </Dropdown>
        )}
      </ul>
    </nav>
  );
}

function Dropdown({
  id,
  label,
  active,
  open,
  onHover,
  onParentClick,
  children,
}: {
  id: MenuId;
  label: string;
  active: boolean;
  open: boolean;
  onHover: (open: boolean) => void;
  onParentClick: () => void;
  children: ReactNode;
}) {
  return (
    <li
      className={`header-nav__item header-nav__item--dropdown${open ? " header-nav__item--open" : ""}`}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
    >
      <button
        type="button"
        className={`header-nav__link header-nav__link--parent${active ? " header-nav__link--active" : ""}`}
        aria-expanded={open}
        aria-haspopup="true"
        aria-controls={`${id}-menu`}
        onClick={onParentClick}
      >
        {label}
      </button>
      <ul
        id={`${id}-menu`}
        className="header-nav__submenu"
        role="menu"
        style={{ display: open ? "block" : "none" }}
      >
        {children}
      </ul>
    </li>
  );
}
