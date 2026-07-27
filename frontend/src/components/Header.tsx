import { NavLink } from "react-router-dom";

export default function Header() {
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
      </ul>
    </nav>
  );
}
