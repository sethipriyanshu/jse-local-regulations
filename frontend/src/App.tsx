import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import AdminPage from './pages/AdminPage'
import HomePage from './pages/HomePage'
import NotFoundPage from './pages/NotFoundPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
