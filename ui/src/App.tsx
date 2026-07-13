import { Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { TopNav } from "@/components/TopNav";
import { SearchProvider } from "@/lib/searchContext";
import { AgentPage } from "@/pages/AgentPage";
import { AgentArenaPage } from "@/pages/AgentArenaPage";
import { EventDetailPage } from "@/pages/EventDetailPage";
import { GetStartedPage } from "@/pages/GetStartedPage";
import { MarketsPage } from "@/pages/MarketsPage";
import { MarketDetailPage } from "@/pages/MarketDetailPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  return (
    <SearchProvider>
      <div className="min-h-screen bg-background text-foreground">
        <TopNav />
        <main className="container py-8">
          <Routes>
            <Route path="/" element={<MarketsPage />} />
            <Route path="/events/:slug" element={<EventDetailPage />} />
            <Route path="/markets/:id" element={<MarketDetailPage />} />
            <Route path="/agents" element={<AgentArenaPage />} />
            <Route path="/agents/:agentId" element={<AgentPage />} />
            <Route path="/agent" element={<Navigate to="/agents" replace />} />
            <Route path="/get-started" element={<GetStartedPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <Toaster position="bottom-right" richColors closeButton />
      </div>
    </SearchProvider>
  );
}
