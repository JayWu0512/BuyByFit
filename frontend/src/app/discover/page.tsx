import { DiscoverView } from "@/components/discover-view";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

export default function DiscoverPage() {
  return (
    <main className="discover-page">
      <div className="page-shell">
        <SiteHeader active="discover" />
      </div>
      <div className="page-shell discover-shell">
        <DiscoverView />
      </div>
      <div className="page-shell">
        <SiteFooter />
      </div>
    </main>
  );
}
