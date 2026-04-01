import { Outlet } from 'react-router-dom';
import { AppSidebar } from './AppSidebar';

export function AppLayout() {
  return (
    <div className="flex h-full">
      <AppSidebar />
      <main className="flex-1 min-w-0 h-full overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
