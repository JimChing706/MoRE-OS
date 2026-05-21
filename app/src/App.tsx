import { Routes, Route } from 'react-router'
import Home from './pages/Home'
import MahjongGame from './pages/MahjongGame'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/mahjong" element={<MahjongGame />} />
    </Routes>
  )
}
