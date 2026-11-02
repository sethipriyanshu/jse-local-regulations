import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="page page-narrow">
      <p className="eyebrow">404</p>
      <h1 className="page-title">Page not found</h1>
      <p className="page-sub">
        <Link to="/">Back to the map</Link>
      </p>
    </div>
  )
}
