import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router";

const REQUEST_ITEMS = [
  { type: "pypi", label: "pypi", to: "/request/pypi" },
  { type: "npm", label: "npm", to: "/request/npm" },
  { type: "nuget", label: "nuget", to: "/request/nuget" },
] as const;

export default function Header() {
  const { pathname } = useLocation();
  const requestActive = pathname.startsWith("/request");
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
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
        <li
          className={`header-nav__item header-nav__item--dropdown${menuOpen ? " header-nav__item--open" : ""}`}
          onMouseEnter={() => setMenuOpen(true)}
          onMouseLeave={() => setMenuOpen(false)}
        >
          <button
            type="button"
            className={`header-nav__link header-nav__link--parent${requestActive ? " header-nav__link--active" : ""}`}
            aria-expanded={menuOpen}
            aria-haspopup="true"
            onClick={() => setMenuOpen((open) => !open)}
          >
            패키지신청
          </button>
          <ul
            className="header-nav__submenu"
            role="menu"
            style={{ display: menuOpen ? "block" : "none" }}
          >
            {REQUEST_ITEMS.map((item) => (
              <li key={item.type}>
                <NavLink
                  to={item.to}
                  className={({ isActive }) =>
                    `header-nav__sublink${isActive ? " header-nav__sublink--active" : ""}`
                  }
                  onClick={() => setMenuOpen(false)}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </li>
      </ul>
    </nav>
  );
}
