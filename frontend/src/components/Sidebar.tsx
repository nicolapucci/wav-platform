import { Bell, FolderKanban, LayoutGrid, ListChecks, LogOut, Settings, UserCircle, Users } from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";

import { clearTokens } from "../api/client";
import { useNotifications } from "../context/NotificationsContext";

const primaryLinks = [
  { to: "/my-tasks", label: "Le mie task", icon: ListChecks },
  { to: "/board", label: "Kanban", icon: LayoutGrid },
  { to: "/projects", label: "Progetti", icon: FolderKanban },
  { to: "/teams", label: "Gruppi", icon: Users },
];

const secondaryLinks = [
  { to: "/settings", label: "Impostazioni", icon: Settings },
  { to: "/profile", label: "Profilo", icon: UserCircle },
];

function linkClassName({ isActive }: { isActive: boolean }) {
  return `sidebar-link${isActive ? " active" : ""}`;
}

export default function Sidebar() {
  const navigate = useNavigate();
  const { unreadCount } = useNotifications();

  function handleLogout() {
    clearTokens();
    navigate("/login");
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">WAV</div>

      <nav className="sidebar-nav">
        {primaryLinks.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={linkClassName}>
            <Icon size={16} strokeWidth={1.75} />
            {label}
          </NavLink>
        ))}

        <NavLink to="/notifications" className={linkClassName}>
          <Bell size={16} strokeWidth={1.75} />
          Notifiche
          {unreadCount > 0 && <span className="sidebar-badge">{unreadCount > 9 ? "9+" : unreadCount}</span>}
        </NavLink>
      </nav>

      <div className="sidebar-footer">
        {secondaryLinks.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={linkClassName}>
            <Icon size={16} strokeWidth={1.75} />
            {label}
          </NavLink>
        ))}
        <button type="button" className="sidebar-link" onClick={handleLogout}>
          <LogOut size={16} strokeWidth={1.75} />
          Esci
        </button>
      </div>
    </aside>
  );
}
