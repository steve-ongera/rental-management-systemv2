import { NavLink } from "react-router-dom";
import {
  FiHome,
  FiCreditCard,
  FiTool,
  FiRepeat,
  FiClock,
  FiUser,
  FiLogOut,
  FiArchive,
} from "react-icons/fi";
import { useAuth } from "../context/AuthContext";

const links = [
  { to: "/", label: "Dashboard", icon: <FiHome /> },
  { to: "/payments", label: "Payments", icon: <FiCreditCard /> },
  { to: "/maintenance", label: "Maintenance", icon: <FiTool /> },
  { to: "/switch-request", label: "Switch House", icon: <FiRepeat /> },
  { to: "/extension-request", label: "Deadline Extension", icon: <FiClock /> },
  { to: "/history", label: "Tenancy History", icon: <FiArchive /> },
  { to: "/profile", label: "My Profile", icon: <FiUser /> },
];

export default function Sider({ open, onClose }) {
  const { logout } = useAuth();

  return (
    <>
      <aside className={`sider ${open ? "open" : ""}`}>
        <div className="sider-brand">
          <div className="sider-brand-mark">RT</div>
          <div>
            <div className="sider-brand-text">RentaTrack</div>
            <div className="sider-brand-tag">Tenant Portal</div>
          </div>
        </div>

        <nav className="sider-nav">
          <div className="sider-section-label">Menu</div>
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === "/"}
              className={({ isActive }) => `sider-link ${isActive ? "active" : ""}`}
              onClick={onClose}
            >
              {link.icon}
              {link.label}
            </NavLink>
          ))}
        </nav>

        <div className="sider-footer">
          <button className="sider-logout" onClick={logout}>
            <FiLogOut />
            Sign out
          </button>
        </div>
      </aside>
      <div className={`sider-backdrop ${open ? "open" : ""}`} onClick={onClose} />
    </>
  );
}