import { NavLink, Outlet } from 'react-router-dom'
import { useAdmin } from '../lib/admin'

export default function Layout() {
  const { isAdmin } = useAdmin()
  const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : '')

  return (
    <div className="app">
      <header className="app-header">
        <NavLink to="/" className="app-title">
          <img className="app-logo" src="/jse-logo.png" alt="Jordan & Skala Engineers" />
          <span>Local Regulations</span>
        </NavLink>
        <nav className="app-nav">
          <NavLink to="/" end className={navClass}>
            Map
          </NavLink>
          <NavLink to="/admin" className={navClass}>
            Admin
          </NavLink>
        </nav>
        {isAdmin && <span className="admin-pill">Admin view</span>}
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
