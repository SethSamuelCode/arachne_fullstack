import { MobileMenuBar, Sidebar } from "@/components/layout";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileMenuBar />
        <main className="flex-1 overflow-auto p-3 sm:p-6 sm:pb-0">{children}</main>
      </div>
    </div>
  );
}
