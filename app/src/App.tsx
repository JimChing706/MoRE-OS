import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router'

const Home = lazy(() => import('./pages/Home'))
const MahjongGame = lazy(() => import('./pages/MahjongGame'))

export default function App() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center text-sm text-muted-foreground">Loading…</div>}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/mahjong" element={<MahjongGame />} />
      </Routes>
    </Suspense>
  )
}
