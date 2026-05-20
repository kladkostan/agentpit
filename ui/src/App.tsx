import { Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { TopNav } from "@/components/TopNav";
import { SearchProvider } from "@/lib/searchContext";
import { EventDetailPage } from "@/pages/EventDetailPage";
import { MarketsPage } from "@/pages/MarketsPage";
import { MarketDetailPage } from "@/pages/MarketDetailPage";

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
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <Toaster position="bottom-right" richColors closeButton />
      </div>
    </SearchProvider>
  );
}
