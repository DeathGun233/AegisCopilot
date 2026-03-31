import { useAppContext } from "../../context/AppContext";
import { formatDateTime } from "../../lib/format";

export function UsersPage() {
  const { users } = useAppContext();

  return (
    <div className="admin-content">
      <section className="dashboard-hero">
        <div>
          <span className="hero-pill">用户管理</span>
          <h2>用户角色与访问权限</h2>
          <p>展示真实账号目录和权限边界，而不是旧版前端切角色的演示方式。</p>
        </div>
      </section>

      <section className="panel-card">
        <div className="panel-head">
          <div>
            <span className="panel-kicker">用户目录</span>
            <h3>工作台账号</h3>
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
                  <span>创建时间</span>
                  <strong>{formatDateTime(user.created_at)}</strong>
                </div>
                <div>
                  <span>权限</span>
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
