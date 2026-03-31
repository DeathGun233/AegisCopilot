import { useAppContext } from "../../context/AppContext";
import { formatDateTime } from "../../lib/format";

export function UsersPage() {
  const { users } = useAppContext();

  return (
    <div className="admin-content">
      <section className="dashboard-hero">
        <div>
          <span className="hero-pill">Users</span>
          <h2>User roles and access</h2>
          <p>Show the real account directory and permission boundaries instead of the old frontend role switcher.</p>
        </div>
      </section>

      <section className="panel-card">
        <div className="panel-head">
          <div>
            <span className="panel-kicker">User Directory</span>
            <h3>Workspace accounts</h3>
          </div>
        </div>

        <div className="user-grid">
          {users.map((user) => (
            <article key={user.id} className="user-list-card">
              <div className="user-row">
                <div className="user-avatar">{user.name.slice(0, 1).toUpperCase()}</div>
                <div>
                  <strong>{user.name}</strong>
                  <p>{user.role_label}</p>
                </div>
              </div>

              <div className="definition-list compact">
                <div>
                  <span>Created at</span>
                  <strong>{formatDateTime(user.created_at)}</strong>
                </div>
                <div>
                  <span>Permissions</span>
                  <strong>{user.permissions.join(", ")}</strong>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
