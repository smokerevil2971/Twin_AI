import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'

export default function AppShell() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar />
      {/* Scrollable main content */}
      <main className="flex-1 overflow-y-auto min-w-0">
        <div className="px-8 py-7 max-w-[1440px] mx-auto w-full">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
