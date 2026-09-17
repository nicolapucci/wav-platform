import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";

import { getAccessToken } from "./api/client";
import Layout from "./components/Layout";
import { NotificationsProvider } from "./context/NotificationsContext";
import HomePage from "./pages/HomePage";
import KanbanViewPage from "./pages/KanbanViewPage";
import LoginPage from "./pages/LoginPage";
import MyTasksPage from "./pages/MyTasksPage";
import NotificationsPage from "./pages/NotificationsPage";
import ProfilePage from "./pages/ProfilePage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import ProjectsPage from "./pages/ProjectsPage";
import SettingsPage from "./pages/SettingsPage";
import TaskDetailPage from "./pages/TaskDetailPage";
import TeamsPage from "./pages/TeamsPage";

function RequireAuth({ children }: { children: React.ReactElement }) {
  return getAccessToken() ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route
          element={
            <RequireAuth>
              {/* Montato una volta sola per tutta la sessione autenticata (non per
                  singola pagina), così il badge nella sidebar resta aggiornato
                  indipendentemente da dove naviga l'utente. */}
              <NotificationsProvider>
                <Layout />
              </NotificationsProvider>
            </RequireAuth>
          }
        >
          <Route path="/" element={<HomePage />} />
          <Route path="/my-tasks" element={<MyTasksPage />} />
          <Route path="/board" element={<KanbanViewPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
          <Route path="/teams" element={<TeamsPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
}

// TODO: allegati sui commenti (presigned URL MinIO/S3).
