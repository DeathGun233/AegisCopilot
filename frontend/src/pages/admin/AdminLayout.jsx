import { NavLink, Outlet } from "react-router-dom";
import { useAppContext } from "../../context/AppContext";

const adminTabs = [
  { to: "/admin/overview", label: "总览" },
  { to: "/admin/knowledge", label: "知识库" },
  { to: "/admin/retrieval-debug", label: "检索调试" },
  { to: "/admin/traces", label: "观测" },
  { to: "/admin/evaluation", label: "评估" },
  { to: "/admin/users", label: "用户" },
];

export function AdminLayout() {
  const { modelCatalog, selectModel } = useAppContext();

  return (
    <div className="page admin-page-shell">
      <header className="page-header admin-header">
        <div>
          <span className="page-kicker">AegisCopilot / 后台</span>
          <h1>管理后台</h1>
        </div>

        {modelCatalog ? (
          <div className="header-toolbar">
            <label className="toolbar-field">
              <span>当前模型</span>
              <select
                value={modelCatalog.active_model}
                onChange={(event) => selectModel(event.target.value).catch(console.error)}
              >
                {modelCatalog.options.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}
      </header>

      <nav className="admin-tabs" aria-label="后台导航">
        {adminTabs.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => (isActive ? "admin-tab active" : "admin-tab")}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </div>
  );
}
