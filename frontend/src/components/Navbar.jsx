import { FiMenu, FiAlertCircle } from "react-icons/fi";
import { useAuth } from "../context/AuthContext";

export default function Navbar({ onMenuClick, isOverdue }) {
  const { user } = useAuth();
  const initials = user
    ? `${user.first_name?.[0] || user.username[0]}${user.last_name?.[0] || ""}`.toUpperCase()
    : "?";

  return (
    <header className="navbar">
      <div className="navbar-left">
        <button className="navbar-menu-btn" onClick={onMenuClick} aria-label="Open menu">
          <FiMenu />
        </button>
        <div>
          <div className="navbar-title">My Rental</div>
          <div className="navbar-subtitle">Track rent, water bills, and requests</div>
        </div>
      </div>

      <div className="navbar-right">
        {isOverdue && (
          <div className="navbar-overdue-pill">
            <FiAlertCircle />
            Rent overdue
          </div>
        )}
        <div className="navbar-user-block">
          <div>
            <div className="navbar-user-name">{user?.full_name || user?.username}</div>
            <div className="navbar-user-role">Tenant</div>
          </div>
          <div className="navbar-avatar">{initials}</div>
        </div>
      </div>
    </header>
  );
}